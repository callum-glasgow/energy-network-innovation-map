import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from core.config import DB, SCOPE, LUNA, EMBEDDING, DIMENSIONS, RECIPE, RETRIEVAL_PROFILE
from core.text import digest, passages

def now(): return datetime.now(timezone.utc).isoformat()

class Store:
    def __init__(self, path=DB):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self._keyword_lock=threading.RLock(); self._keyword_cache=None
        self._profile_hash_cache={}; self._profile_hash_lock=threading.RLock()
        self._passage_cache=None; self._passage_lock=threading.RLock()
        self._connections=threading.local()
        with self.connect() as c:
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript('''
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY, record TEXT NOT NULL, semantic_hash TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS passages(id TEXT PRIMARY KEY, project_id TEXT, field TEXT, text TEXT, hash TEXT);
            CREATE TABLE IF NOT EXISTS summaries(cache_key TEXT PRIMARY KEY, project_id TEXT, source_hash TEXT, text TEXT, record TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS vectors(cache_key TEXT PRIMARY KEY, model TEXT, dimensions INTEGER, vector TEXT);
            CREATE TABLE IF NOT EXISTS passage_vectors(cache_key TEXT PRIMARY KEY, model TEXT, dimensions INTEGER, vector TEXT);
            CREATE TABLE IF NOT EXISTS rerank_cache(cache_key TEXT PRIMARY KEY, record TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS rerank_pairs(cache_key TEXT PRIMARY KEY, score REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY, record TEXT);
            CREATE INDEX IF NOT EXISTS passages_project_field_id ON passages(project_id,field,id);
            CREATE TABLE IF NOT EXISTS project_references(project_id TEXT PRIMARY KEY, normalized TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS project_references_normalized ON project_references(normalized,project_id);
            ''')
            from core.keyword import reference_key
            missing=c.execute('SELECT projects.id,projects.record FROM projects LEFT JOIN project_references ON projects.id=project_references.project_id WHERE project_references.project_id IS NULL').fetchall()
            c.executemany('INSERT INTO project_references VALUES (?,?)',[(r['id'],reference_key(json.loads(r['record'])['reference'])) for r in missing])
            c.execute('INSERT OR IGNORE INTO meta VALUES (?,?)',('search_revision',json.dumps(uuid.uuid4().hex)))
            try:
                c.execute('CREATE VIRTUAL TABLE IF NOT EXISTS lexical USING fts5(id UNINDEXED, reference, title, narrative)')
                self.fts=True
            except sqlite3.OperationalError: self.fts=False
    @contextmanager
    def connect(self):
        borrowed=getattr(self._connections,'connection',None)
        if borrowed is not None:
            with borrowed: yield borrowed
            return
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row
        try:
            with c: yield c
        finally: c.close()

    @contextmanager
    def session(self):
        # Reuse one connection within a search, never across request threads.
        # Individual connect() blocks still commit/roll back independently.
        if getattr(self._connections,'connection',None) is not None:
            yield
            return
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row
        self._connections.connection=c
        try: yield
        finally:
            del self._connections.connection
            c.close()

    def keyword_snapshot(self):
        # Revision, projects and passages come from one committed SQLite snapshot.
        # Other Store instances (including CLI imports) invalidate this cache too.
        from core.keyword import KeywordIndex
        with self._keyword_lock, self.connect() as c:
            c.execute('BEGIN')
            revision=c.execute('SELECT value FROM meta WHERE key=?',('search_revision',)).fetchone()[0]
            if self._keyword_cache and self._keyword_cache[0]==revision:
                return self._keyword_cache[1]
            records=[json.loads(r[0]) for r in c.execute('SELECT record FROM projects WHERE active=1')]
            rows=[dict(r) for r in c.execute('SELECT passages.* FROM passages JOIN projects ON projects.id=passages.project_id WHERE projects.active=1 ORDER BY passages.field,passages.id')]
            index=KeywordIndex(records,rows)
            index.revision=revision
            self._keyword_cache=(revision,index)
            return index
    def meta(self,key,value=None):
        with self.connect() as c:
            if value is not None: c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',(key,json.dumps(value))); return value
            r=c.execute('SELECT value FROM meta WHERE key=?',(key,)).fetchone()
            return json.loads(r[0]) if r else None
    def upsert(self,records,complete=False):
        from core.keyword import reference_key
        ids=[r['id'] for r in records]
        if len(ids)!=len(set(ids)): raise ValueError('Duplicate project identities')
        if complete and not ids: raise ValueError('Refusing empty complete snapshot')
        with self.connect() as c:
            for record in records:
                h=digest(json.dumps({'title':record['title'],'fields':record['fields']},sort_keys=True))
                old=c.execute('SELECT semantic_hash,record FROM projects WHERE id=?',(record['id'],)).fetchone()
                record['content_changed_at']=json.loads(old['record']).get('content_changed_at') if old and old['semantic_hash']==h else now()
                record['semantic_hash']=h
                c.execute('INSERT OR REPLACE INTO projects VALUES (?,?,?,1)',(record['id'],json.dumps(record),h))
                c.execute('INSERT OR REPLACE INTO project_references VALUES (?,?)',(record['id'],reference_key(record['reference'])))
                if not old or old['semantic_hash']!=h:
                    c.execute('DELETE FROM passages WHERE project_id=?',(record['id'],))
                    for p in passages(record['id'],record['fields']):
                        c.execute('INSERT INTO passages VALUES (?,?,?,?,?)',(p['id'],p['project_id'],p['field'],p['text'],p['hash']))
                if self.fts:
                    c.execute('DELETE FROM lexical WHERE id=?',(record['id'],))
                    c.execute('INSERT INTO lexical VALUES (?,?,?,?)',(record['id'],record['reference'],record['title'],' '.join(record['fields'].values())))
            if complete:
                placeholders=','.join('?' for _ in ids)
                c.execute(f'UPDATE projects SET active=0 WHERE id NOT IN ({placeholders})',ids)
            c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('search_revision',json.dumps(uuid.uuid4().hex)))
        return len(records)
    def projects(self):
        with self.connect() as c: return [json.loads(r[0]) for r in c.execute('SELECT record FROM projects WHERE active=1')]
    def exact_projects(self,normalized):
        if not normalized:return []
        with self.connect() as c:
            return [json.loads(r[0]) for r in c.execute('SELECT projects.record FROM project_references JOIN projects ON projects.id=project_references.project_id WHERE project_references.normalized=? AND projects.active=1',(normalized,))]
    def project(self,id):
        with self.connect() as c: r=c.execute('SELECT record FROM projects WHERE id=? AND active=1',(id,)).fetchone()
        if not r: raise KeyError(id)
        return json.loads(r[0])
    def passages(self,id):
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM passages WHERE project_id=? ORDER BY field,id',(id,))]
    def summary_source_hash(self,p):
        from core.retrieval_profile import RECIPE as PROFILE_RECIPE, source_hash
        if RECIPE == PROFILE_RECIPE:
            return source_hash(self,p)
        from core.retrieval_summary import RECIPE as SEARCH_RECIPE, build_request, SYSTEM_PROMPT, REASONING_EFFORT
        if RECIPE == SEARCH_RECIPE:
            return digest(SYSTEM_PROMPT+REASONING_EFFORT+json.dumps(build_request(self,p),sort_keys=True,ensure_ascii=False))
        return p['semantic_hash']
    def summary_key(self,p): return digest(self.summary_source_hash(p)+LUNA+RECIPE)
    def summary(self,p):
        with self.connect() as c: r=c.execute('SELECT record FROM summaries WHERE cache_key=?',(self.summary_key(p),)).fetchone()
        return json.loads(r[0]) if r else None
    def summary_text(self,p):
        # Search needs the embedded body, not the large internal extraction audit.
        with self.connect() as c:r=c.execute('SELECT text FROM summaries WHERE cache_key=?',(self.summary_key(p),)).fetchone()
        return r[0] if r else None
    def save_summary(self,p,record):
        source_hash=self.summary_source_hash(p)
        record.update({'model':LUNA,'recipe':RECIPE,'source_hash':source_hash,'created_at':now()})
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO summaries VALUES (?,?,?,?,?,?)',(self.summary_key(p),p['id'],source_hash,record['summary'],json.dumps(record),record['created_at']))
            c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('graph_profile_revision',json.dumps(uuid.uuid4().hex)))
    def vector_key(self,text): return digest(text+EMBEDDING+str(DIMENSIONS)+RECIPE)
    def vector(self,text):
        with self.connect() as c: r=c.execute('SELECT vector FROM vectors WHERE cache_key=? AND model=? AND dimensions=?',(self.vector_key(text),EMBEDDING,DIMENSIONS)).fetchone()
        return json.loads(r[0]) if r else None
    def save_vector(self,text,v):
        with self.connect() as c:
            c.execute('INSERT OR REPLACE INTO vectors VALUES (?,?,?,?)',(self.vector_key(text),EMBEDDING,DIMENSIONS,json.dumps(v)))
            # Query embeddings do not invalidate the portfolio. Profile vector changes do.
            if '\n' in text and c.execute('SELECT 1 FROM summaries WHERE text=? LIMIT 1',(text.split('\n',1)[1],)).fetchone():
                c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('graph_profile_revision',json.dumps(uuid.uuid4().hex)))
    def save_passage_vectors(self,rows):
        import math
        from core.passage_search import key
        prepared=[]
        for text,vector in rows:
            if len(vector)!=DIMENSIONS or any(not isinstance(x,(int,float)) or not math.isfinite(x) for x in vector):
                raise ValueError('Invalid passage vector')
            norm=math.sqrt(sum(x*x for x in vector))
            if not norm:raise ValueError('Zero passage vector')
            prepared.append((key(text),EMBEDDING,DIMENSIONS,json.dumps([x/norm for x in vector])))
        with self.connect() as c:
            c.executemany('INSERT OR REPLACE INTO passage_vectors VALUES (?,?,?,?)',prepared)
            c.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('passage_vector_revision',json.dumps(uuid.uuid4().hex)))
    def status(self):
        ps=self.projects(); summaries=[self.summary_text(p) for p in ps]
        indexed=sum(bool(s and self.vector(p['title']+'\n'+s)) for p,s in zip(ps,summaries))
        return {'scope':SCOPE,'projects':len(ps),'summarised':sum(bool(s) for s in summaries),'indexed':indexed,'pending':len(ps)-indexed,'fts5':self.fts,'catalogue_last_checked_at':self.meta('catalogue_last_checked_at'),'last_successful_full_refresh_at':self.meta('last_successful_full_refresh_at'),'catalogue_count':self.meta('catalogue_count'),'refresh_error':self.meta('refresh_error'),'summary_model':LUNA,'embedding_model':EMBEDDING,'dimensions':DIMENSIONS,'retrieval_profile':RETRIEVAL_PROFILE,'summary_recipe':RECIPE}
