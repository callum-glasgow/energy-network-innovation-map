"""Exact symmetric project comparisons, entirely from compatible cached vectors."""
from collections import Counter
import json

import numpy as np

from core.config import DIMENSIONS, EMBEDDING
from core.passage_search import chunks, key as passage_key


def unit(value):
    vector = np.asarray(json.loads(value) if isinstance(value, str) else value, dtype=np.float32)
    if vector.shape != (DIMENSIONS,) or not np.isfinite(vector).all():
        return None
    norm = np.linalg.norm(vector)
    return vector / norm if np.isfinite(norm) and norm > 0 else None


def percentile_scores(matrix):
    n = len(matrix)
    mask = np.triu(np.isfinite(matrix), 1)
    distribution = np.sort(matrix[mask])
    result = np.full_like(matrix, np.nan)
    if len(distribution):
        valid = np.isfinite(matrix)
        # Mid-rank ties; fixed full-corpus transform, not a probability or per-filter rank.
        result[valid] = (np.searchsorted(distribution, matrix[valid], side='left') +
                         np.searchsorted(distribution, matrix[valid], side='right')) / (2 * len(distribution))
    np.fill_diagonal(result, np.nan)
    return result


def compute_similarity(store, projects, index):
    n = len(projects)
    with store.connect() as c:
        vectors = {r['cache_key']: r['vector'] for r in c.execute(
            'SELECT cache_key,vector FROM vectors WHERE model=? AND dimensions=?', (EMBEDDING, DIMENSIONS))}
        original = {r['cache_key']: r['vector'] for r in c.execute(
            'SELECT cache_key,vector FROM passage_vectors WHERE model=? AND dimensions=?', (EMBEDDING, DIMENSIONS))}
    profiles = np.full((n, n), np.nan, dtype=np.float32)
    profile_matrix = np.zeros((n, DIMENSIONS), dtype=np.float32)
    available = []
    for i, project in enumerate(projects):
        summary = store.summary_text(project)
        text = project['title'] + '\n' + summary if summary else ''
        vector = unit(vectors[store.vector_key(text)]) if text and store.vector_key(text) in vectors else None
        if vector is not None:
            profile_matrix[i] = vector
            available.append(i)
    if available:
        profiles[np.ix_(available, available)] = np.clip(np.einsum('ik,jk->ij', profile_matrix[available], profile_matrix[available], optimize=False), -1, 1)

    candidates = chunks(projects, index.passages)
    selected, source_vectors = [], []
    expected = Counter(p['project_id'] for p in candidates)
    for passage in candidates:
        value = original.get(passage_key(passage['text']))
        vector = unit(value) if value else None
        if vector is not None:
            selected.append({k: passage[k] for k in ('project_id', 'source_id', 'field')})
            source_vectors.append(vector)
    by_project = {p['id']: [] for p in projects}
    for i, passage in enumerate(selected):
        by_project[passage['project_id']].append(i)
    source = np.full((n, n), np.nan, dtype=np.float32)
    centroid = np.full_like(source, np.nan)
    # Evidence indices refer to original passage IDs, never internal profile text.
    evidence = np.full((n, n, 3, 2), -1, dtype=np.int32)
    coverage = []
    weights = []
    for i, p in enumerate(projects):
        indices = by_project[p['id']]
        counts = Counter(selected[k]['field'] for k in indices)
        weights.append(np.asarray([1 / counts[selected[k]['field']] for k in indices], dtype=np.float32))
        coverage.append({'profile': i in available, 'passages': len(indices), 'expected': expected[p['id']],
                         'complete': bool(indices) and len(indices) == expected[p['id']]})
    if source_vectors:
        source_matrix = np.asarray(source_vectors, dtype=np.float32)
        centroids = {}
        for i, p in enumerate(projects):
            ids = by_project[p['id']]
            if ids:
                vector = np.average(source_matrix[ids], weights=weights[i], axis=0)
                centroids[i] = vector / max(float(np.linalg.norm(vector)), 1e-12)
        for i, a in enumerate(projects):
            aa = by_project[a['id']]
            if not aa:
                continue
            # Bound peak passage-score memory by this project's passages, not the
            # square of the whole corpus. Scores retain the exact same definition.
            row_scores = np.clip(np.einsum('ik,jk->ij', source_matrix[aa], source_matrix, optimize=False), -1, 1)
            for j in range(i + 1, n):
                bb = by_project[projects[j]['id']]
                if not bb:
                    continue
                block = row_scores[:, bb]
                score = (np.average(block.max(axis=1), weights=weights[i]) +
                         np.average(block.max(axis=0), weights=weights[j])) / 2
                source[i, j] = source[j, i] = score
                centroid[i, j] = centroid[j, i] = centroids[i] @ centroids[j]
                used_a, used_b, matches = set(), set(), []
                for flat in np.argsort(-block, axis=None, kind='stable'):
                    ai, bi = np.unravel_index(flat, block.shape)
                    if ai in used_a or bi in used_b:
                        continue
                    matches.append([aa[ai], bb[bi]])
                    used_a.add(ai); used_b.add(bi)
                    if len(matches) == 3:
                        break
                evidence[i, j, :len(matches)] = matches
                evidence[j, i, :len(matches)] = [m[::-1] for m in matches]
    for matrix in (profiles, source, centroid):
        np.fill_diagonal(matrix, np.nan)
    profile_rank, source_rank = percentile_scores(profiles), percentile_scores(source)
    balanced = (profile_rank + source_rank) / 2
    # A project without either complete channel is visible but has no balanced score.
    for i, cover in enumerate(coverage):
        if not cover['complete'] or not cover['profile']:
            balanced[i, :] = balanced[:, i] = np.nan
    return {'profile': profiles, 'source': source, 'centroid': centroid, 'balanced': balanced,
            'profile_rank': profile_rank, 'source_rank': source_rank, 'evidence': evidence}, coverage, selected
