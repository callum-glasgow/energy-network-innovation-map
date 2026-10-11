"""Atomic, durable reservations. Ambiguous failures retain their full reservation."""
import json
import math
import sqlite3
import uuid
from pathlib import Path
from core.config import LEDGER, budget_cap, LUNA
from core.storage import now

RATES={LUNA:(0.10,0.50),'text-embedding-3-small':(0.02,0),'text-embedding-3-large':(0.13,0)}

class BudgetExceeded(ValueError): pass

class Budget:
    def __init__(self,path=LEDGER,cap=None):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        self.cap=budget_cap() if cap is None else float(cap)
        if not math.isfinite(self.cap) or not 0<=self.cap<=5: raise ValueError('Budget cannot exceed $5')
        with self.connect() as c: c.execute('CREATE TABLE IF NOT EXISTS calls(id TEXT PRIMARY KEY,created_at TEXT,model TEXT,purpose TEXT,reserved REAL,charged REAL,state TEXT,usage TEXT)')
    def connect(self):
        c=sqlite3.connect(self.path,timeout=30); c.row_factory=sqlite3.Row; return c
    def reserve(self,model,payload,max_output,purpose):
        if model not in RATES: raise ValueError('Unpriced or unauthorised model blocked')
        # UTF-8 bytes bound text token count; full JSON plus 4096 bounds message overhead.
        # 2x verified standard rates cover cache writes and regional premiums.
        i,o=RATES[model]; upper=((len(json.dumps(payload,ensure_ascii=False).encode())+4096)*i+max_output*o)*2/1e6
        id=str(uuid.uuid4())
        with self.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            used=c.execute('SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM calls').fetchone()[0]
            if used+upper>self.cap: raise BudgetExceeded(f'API budget exhausted: ${used:.6f} accounted; next reservation ${upper:.6f}; cap ${self.cap:.2f}')
            c.execute('INSERT INTO calls VALUES (?,?,?,?,?,NULL,?,NULL)',(id,now(),model,purpose,upper,'reserved'))
        return id
    def settle(self,id,usage):
        with self.connect() as c:
            r=c.execute('SELECT * FROM calls WHERE id=?',(id,)).fetchone()
            i,o=RATES[r['model']]
            inp=usage.get('input_tokens',usage.get('prompt_tokens')); out=usage.get('output_tokens',usage.get('completion_tokens',0))
            if not isinstance(inp,int) or not isinstance(out,int) or inp<0 or out<0: return
            actual=(inp*i+out*o)/1e6
            # Conservative accounting never understates cache-write/regional charges.
            accounted=actual*1.375
            c.execute('UPDATE calls SET charged=?, state=?,usage=? WHERE id=?',(max(accounted,r['reserved']) if accounted>r['reserved'] else accounted,'completed',json.dumps(dict(usage,base_cost_usd=actual)),id))
    def fail(self,id):
        with self.connect() as c: c.execute("UPDATE calls SET state='uncertain' WHERE id=?",(id,))
    def status(self):
        with self.connect() as c: rows=[dict(r) for r in c.execute('SELECT * FROM calls ORDER BY created_at')]
        used=sum(r['charged'] if r['charged'] is not None else r['reserved'] for r in rows)
        return {'cap_usd':self.cap,'accounted_usd':used,'remaining_usd':max(0,self.cap-used),'base_cost_usd':sum(json.loads(r['usage']).get('base_cost_usd',0) for r in rows if r['usage']),'calls':len(rows),'uncertain_calls':sum(r['state']!='completed' for r in rows),'models':sorted(set(r['model'] for r in rows))}
