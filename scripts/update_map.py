"""Preview or apply a resumable ENA import, incremental indexing and static map build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
from contextlib import contextmanager
from adapters.ena.downloads import read_rows, import_download, needs_catalogue, comparable_record
from core.config import DATA, DB, ROOT, OWNERS, RECIPE, LUNA, EMBEDDING, DIMENSIONS, LEDGER, budget_cap
from core.storage import Store, now
from core.text import digest
from scripts.index_passages import missing_passages
from core.passage_search import key as passage_key

REVISION_KEYS = ('search_revision', 'graph_profile_revision', 'passage_vector_revision', 'retrieval_term_overrides')
IMPORT_META = REVISION_KEYS + ('last_successful_full_refresh_at', 'catalogue_last_checked_at',
    'catalogue_count', 'catalogue_scope', 'refresh_error', 'last_file_import_at', 'last_map_update_job')


def save_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(temporary, path)


def revisions(store):
    with store.connect() as connection:
        return {key: (row[0] if (row := connection.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()) else None)
                for key in REVISION_KEYS}


def copy_database(source, destination):
    with sqlite3.connect(source) as original, sqlite3.connect(destination) as copied:
        original.backup(copied)


def budget_status():
    # Preview must not create or reset the spend ledger.
    cap = budget_cap(); used = 0
    if LEDGER.exists():
        with sqlite3.connect(f'file:{LEDGER}?mode=ro', uri=True) as connection:
            used = connection.execute('SELECT COALESCE(SUM(COALESCE(charged,reserved)),0) FROM calls').fetchone()[0]
    return {'cap_usd': cap, 'accounted_usd': used, 'remaining_usd': max(0, cap-used)}


def coverage(store):
    profiles, vectors, unavailable = [], [], []
    from core.retrieval_profile import request_for
    with store.session():
        for project in store.projects():
            if not project['fields'] or not request_for(store, project)['passages']:
                unavailable.append(project['id']); continue
            summary = store.summary(project)
            if not summary:
                profiles.append(project['id'])
            elif not store.vector(project['title'] + '\n' + summary['summary']):
                vectors.append(project['id'])
        active, pending = missing_passages(store)
    unique = {passage_key(chunk['text']): chunk for chunk in pending}
    return {'luna_profiles': profiles, 'profile_embeddings': vectors,
            'original_passage_embeddings': list(unique.values()),
            'active_original_passages': len(active), 'without_indexable_text': unavailable}


def coverage_counts(pending):
    result = {key: len(value) if isinstance(value, list) else value for key, value in pending.items()}
    # Every newly generated profile also needs its own embedding.
    result['profile_embeddings'] += len(pending['luna_profiles'])
    return result


def apply_records(store, records, scope, replace=False):
    before = {p['id']: p for p in store.projects()}
    counts = dict(new=0, narrative_changes=0, metadata_changes=0, unchanged=0, retained=0, deactivated=0)
    for record in records:
        old = before.get(record['id'])
        if not old:
            counts['new'] += 1
        elif (old['title'], old['fields']) != (record['title'], record['fields']):
            counts['narrative_changes'] += 1
        elif comparable_record(old) != comparable_record(record):
            counts['metadata_changes'] += 1
        else:
            counts['unchanged'] += 1
    store.upsert(records)
    incoming = {p['id'] for p in records}
    removed = [p['id'] for p in before.values() if p['id'] not in incoming and (scope == 'all' or p['owner'] in OWNERS)] if replace else []
    if removed:
        with store.connect() as connection:
            connection.executemany('UPDATE projects SET active=0 WHERE id=?', [(identity,) for identity in removed])
    counts['deactivated'] = len(removed)
    counts['retained'] = len(set(before)-incoming-set(removed))
    store.meta('last_successful_full_refresh_at', '')
    store.meta('catalogue_last_checked_at', '')
    store.meta('refresh_error', '')
    store.meta('catalogue_scope', sorted({p['owner'] for p in store.projects()}))
    store.meta('catalogue_count', len(store.projects()))
    store.meta('last_file_import_at', now())
    return counts


def promote_database(live, staged, baseline):
    """One transaction; retain reports and query/reranker caches written during indexing."""
    with live.connect() as connection:
        connection.execute('ATTACH DATABASE ? AS prepared', (str(staged.path),))
        connection.execute('BEGIN IMMEDIATE')
        current = {key: (row[0] if (row := connection.execute('SELECT value FROM main.meta WHERE key=?', (key,)).fetchone()) else None) for key in REVISION_KEYS}
        if current != baseline:
            raise ValueError('The source/index changed during this update. Start a new update from the current database; no live records replaced.')
        for table in ('projects', 'passages', 'project_references', 'lexical'):
            if table == 'lexical' and not live.fts:
                continue
            connection.execute(f'DELETE FROM main.{table}')
            connection.execute(f'INSERT INTO main.{table} SELECT * FROM prepared.{table}')
        for table in ('summaries', 'vectors', 'passage_vectors'):
            connection.execute(f'INSERT OR IGNORE INTO main.{table} SELECT * FROM prepared.{table}')
        for name in IMPORT_META:
            connection.execute('INSERT OR REPLACE INTO main.meta SELECT key,value FROM prepared.meta WHERE key=?', (name,))


@contextmanager
def update_lock(folder):
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    for name in ('refresh.lock', 'enrichment.lock'):
        if (DATA/name).exists():
            raise ValueError(f'{name} exists: finish the active job before updating the map')
    path = folder/'map-update.lock'
    try:
        handle = path.open('x')
    except FileExistsError:
        raise ValueError(f'{path} exists. Remove it only after checking that the previous update process has stopped.') from None
    try:
        handle.write(str(os.getpid())); handle.close(); yield
    finally:
        path.unlink(missing_ok=True)


def finish_files(job, site, archive):
    from scripts.build_map import replace_directory
    from scripts.map_release import validate_site, sha256
    validate_site(job/'site')
    recorded = json.loads((job/'build.json').read_text())
    if sha256(job/'energy-network-map.zip') != recorded['archive_sha256']:
        raise ValueError('Prepared archive changed; rebuild the update')
    site, archive = Path(site), Path(archive)
    site.parent.mkdir(parents=True, exist_ok=True); archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.map-promote-', dir=site.parent) as temporary:
        copied = Path(temporary)/'site'; shutil.copytree(job/'site', copied)
        pending = archive.with_name(archive.name+'.tmp'); shutil.copy2(job/'energy-network-map.zip', pending)
        replace_directory(copied, site); os.replace(pending, archive)


def update(source, *, database=DB, scope='spen', replace=False, apply=False, live=False,
           catalogue_path=None, mapping_path=None, work_dir=None, model=None, builder=None,
           site=None, archive=None):
    database = Path(database).resolve()
    store = Store(database) if database.is_file() or apply else None
    baseline = revisions(store) if store else None
    rows = read_rows(source)
    mapping = json.loads(Path(mapping_path).read_text()) if mapping_path else None
    envelope = None
    if Path(source).suffix.lower() == '.json':
        envelope = json.loads(Path(source).read_text(encoding='utf-8-sig'))
        if isinstance(envelope, dict) and mapping is None:
            mapping = envelope.get('field_mapping')
    cat = None
    if needs_catalogue(rows):
        if catalogue_path:
            cat = json.loads(Path(catalogue_path).read_text())
            if isinstance(cat, dict):cat = cat.get('catalogue', cat)
        elif Path(source).suffix.lower() == '.json':
            if isinstance(envelope, dict):cat = envelope.get('catalogue')
        if cat is None:
            from adapters.ena.client import catalogue
            print('Resolving spreadsheet identities against the ENA catalogue (no model calls).', flush=True)
            cat = catalogue()
    records, imported = import_download(rows, store.projects() if store else [], scope, cat, mapping)
    if imported['errors']:
        raise ValueError('Import blocked; no live data changed:\n' + json.dumps(imported, indent=2))
    if store and revisions(store) != baseline:
        raise ValueError('Live source/index changed during import preparation. Repeat against the current database.')
    recipe_files = [ROOT/'core/retrieval_profile.py', ROOT/'core/retrieval_summary.py',
                    ROOT/'core/retrieval_profile_prompt.txt', ROOT/'core/retrieval_profile_schema.json']
    signature = {'input': hashlib.sha256(Path(source).read_bytes()).hexdigest(), 'database': str(database),
                 'scope': scope, 'replace': replace, 'mapping': mapping, 'identities': [p['id'] for p in records],
                 'models': [RECIPE,LUNA,EMBEDDING,DIMENSIONS],
                 'prompts': [hashlib.sha256(p.read_bytes()).hexdigest() for p in recipe_files]}
    from scripts.map_release import source_fingerprint
    signature['source_fingerprint'] = source_fingerprint(ROOT)
    identifier = digest(json.dumps(signature, sort_keys=True))[:20]
    work = Path(work_dir) if work_dir else database.parent/'map-updates'
    site = Path(site) if site else ROOT/'frontend/map-dist'
    archive = Path(archive) if archive else ROOT/'outputs/energy-network-map.zip'
    if not apply:
        with tempfile.TemporaryDirectory(prefix='map-preview-') as temporary:
            prepared_path = Path(temporary)/'prepared.sqlite3'
            if store:copy_database(database, prepared_path)
            prepared = Store(prepared_path); changes = apply_records(prepared, records, scope, replace)
            pending = coverage(prepared)
            entries = len(prepared.projects())
        result = {'mode': 'preview', 'import': imported, 'changes': changes, 'entries': entries,
                  'pending': coverage_counts(pending), 'budget': budget_status(),
                  'job': str(work/identifier), 'paid_calls_made': 0}
        print(json.dumps(result, indent=2)); return result
    with update_lock(work):
        job = work/identifier; job.mkdir(parents=True, exist_ok=True); state_path = job/'state.json'
        if state_path.exists():
            state = json.loads(state_path.read_text())
            if state['signature'] != signature:raise ValueError('Update signature mismatch')
            expected = state.get('promoted_revision', state['baseline'])
            if state['phase'] == 'indexing' and store.meta('last_map_update_job') == identifier:
                # Recover the small window between the database transaction and the state file rename.
                if baseline == revisions(Store(job/'prepared.sqlite3')):
                    state.update(phase='promoted', promoted_revision=baseline)
                    save_json(state_path, state)
                    expected = baseline
            if baseline != expected:
                # Reuse expensive immutable model results without accepting an out-of-date source baseline.
                raise ValueError(f'Live data changed since this job started. Preserve {job} and use --work-dir data/map-updates-new for a fresh update.')
            if state['phase'] == 'complete':
                print(f'Update already completed: {job}. Rebuilding the source alone: python -m scripts.build_map')
                return state
        else:
            copy_database(database, job/'prepared.sqlite3')
            state = {'signature': signature, 'baseline': baseline, 'phase': 'indexing', 'started_at': now(),
                     'changes': apply_records(Store(job/'prepared.sqlite3'), records, scope, replace)}
            save_json(state_path, state)
        prepared = Store(job/'prepared.sqlite3')
        if state['phase'] != 'promoted':
            pending = coverage(prepared)
            print(json.dumps({'changes': state['changes'], 'pending': coverage_counts(pending),
                              'budget': budget_status(), 'resume_job': str(job)}, indent=2), flush=True)
            paid = pending['luna_profiles'] or pending['profile_embeddings'] or pending['original_passage_embeddings']
            if paid and not live:
                raise ValueError('Missing model outputs. Review the preview, then repeat with --apply --live to authorise paid calls under the existing $5 ledger. Current map is unchanged.')
            if paid:
                from adapters.models.openai import OpenAI, index_project
                model = model or OpenAI()
                identities = pending['luna_profiles'] + pending['profile_embeddings']
                for number, identity in enumerate(identities, 1):
                    index_project(prepared, model, prepared.project(identity))
                    print(f'Indexed project {number}/{len(identities)}', flush=True)
                for number, chunk in enumerate(pending['original_passage_embeddings'], 1):
                    prepared.save_passage_vectors([(chunk['text'], model.embedding(chunk['text'], 'original passage embedding'))])
                    print(f'Embedded source passage {number}/{len(pending["original_passage_embeddings"])}', flush=True)
            remaining = coverage(prepared)
            if remaining['luna_profiles'] or remaining['profile_embeddings'] or remaining['original_passage_embeddings']:
                raise ValueError('Index coverage incomplete. Prepared progress is retained; live data is unchanged.')
            if revisions(store) != state['baseline']:
                raise ValueError('Live source/index changed while indexing; current map is unchanged')
            if builder is None:
                from scripts.build_map import build
                builder = build
            builder(destination=job/'site', database=prepared.path, archive=job/'energy-network-map.zip', report=job/'build.json', compatibility=False)
            if source_fingerprint(ROOT) != signature['source_fingerprint']:
                raise ValueError('Source changed during preparation. Repeat with the current code; prepared model results are retained.')
            backup = database.parent/'backups'/f'{database.stem}-{now()[:19].replace(":", "-")}-{identifier}.sqlite3'
            backup.parent.mkdir(parents=True, exist_ok=True); copy_database(database, backup)
            # A marker in the same SQLite transaction makes recovery safe even if the process stops before state.json is saved.
            prepared.meta('last_map_update_job', identifier)
            state['backup'] = str(backup); save_json(state_path, state)
            promote_database(store, prepared, state['baseline'])
            state.update(phase='promoted', promoted_revision=revisions(store), backup=str(backup))
            save_json(state_path, state)
        finish_files(job, site, archive)
        state.update(phase='complete', completed_at=now(), site=str(site), archive=str(archive))
        save_json(state_path, state)
        print(json.dumps(state, indent=2)); return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--scope', choices=['spen','all'], default='spen')
    parser.add_argument('--database', type=Path, default=DB)
    parser.add_argument('--catalogue', type=Path); parser.add_argument('--mapping', type=Path)
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--replace', action='store_true', help='Deactivate absent entries in the selected scope; only for a complete export')
    parser.add_argument('--apply', action='store_true'); parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    try:
        update(args.source, database=args.database, scope=args.scope, replace=args.replace, apply=args.apply, live=args.live,
               catalogue_path=args.catalogue, mapping_path=args.mapping, work_dir=args.work_dir)
    except (ValueError, OSError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')
if __name__ == '__main__':main()
