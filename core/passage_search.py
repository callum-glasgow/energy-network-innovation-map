"""Original-source passage embeddings, independent of the Luna recipe."""
from core.config import EMBEDDING, DIMENSIONS
from core.retrieval_summary import PRIMARY, CONTEXT, retrieval_text
from core.text import digest

VERSION = 'original-passage-v1'
EMPTY = {'true', 'false', 'na', 'n/a', 'none', 'not applicable', '-', '[]', '{}'}


def chunks(projects, passages_by_project):
    result = []
    for project in projects:
        seen = set()
        for passage in sorted(passages_by_project[project['id']], key=lambda p: (p['field'], p['id'])):
            field = passage['field']
            if field not in PRIMARY and field not in CONTEXT:
                continue
            text = retrieval_text(passage['text'])
            if text.strip().casefold().rstrip('.') in EMPTY or not text.strip() or text.casefold() in seen:
                continue
            seen.add(text.casefold())
            label = PRIMARY.get(field, CONTEXT.get(field, field))
            result.append({'project_id': project['id'], 'source_id': passage['id'], 'field': field,
                           'text': project['title'] + '\n' + label + '\n' + text})
    return result


def key(text):
    return digest(VERSION + EMBEDDING + str(DIMENSIONS) + text)


def retrieve(store, index, projects, query_vector):
    """Collapse by best passage before ranks: no vote for every chunk."""
    import numpy as np
    revision = (index.revision, EMBEDDING, DIMENSIONS, store.meta('passage_vector_revision'),
                tuple(p['id'] for p in projects))
    with store._passage_lock:
        cached = store._passage_cache
        if not cached or cached[0] != revision:
            active = chunks(projects, index.passages)
            with store.connect() as connection:
                rows = {row['cache_key']: row['vector'] for row in connection.execute(
                    'SELECT cache_key,vector FROM passage_vectors WHERE model=? AND dimensions=?',
                    (EMBEDDING, DIMENSIONS))}
            import json
            selected = [c for c in active if key(c['text']) in rows]
            matrix = np.asarray([json.loads(rows[key(c['text'])]) for c in selected], dtype=np.float32)
            cached = (revision, selected, matrix, len(active))
            store._passage_cache = cached
    _, selected, matrix, expected = cached
    best = {}
    if selected and query_vector is not None:
        values = np.einsum('ij,j->i', matrix, np.asarray(query_vector, dtype=np.float32), optimize=False)
        for chunk, value in zip(selected, values):
            pid = chunk['project_id']
            if pid not in best or value > best[pid]['score']:
                best[pid] = {'score': float(value), 'source_id': chunk['source_id']}
    return best, {'indexed': len(selected), 'expected': expected, 'complete': len(selected) == expected,
                  'projects_indexed': len({c['project_id'] for c in selected}),
                  'projects_expected': len(projects)}
