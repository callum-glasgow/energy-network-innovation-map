"""Precomputed, revisioned portfolio graphs. Browser receives no vectors or physics."""
import json
import gzip
import math
import os
import random
import threading
import time
import tempfile
from collections import Counter

# igraph imports its optional plotting helpers. Give their font cache a writable,
# reusable home without changing an explicitly configured user path.
os.environ.setdefault('MPLCONFIGDIR', os.path.join(tempfile.gettempdir(), 'smart-ema-matplotlib'))
import igraph as ig
import networkx as nx
import numpy as np

from core.config import DIMENSIONS, EMBEDDING, RECIPE
from core.retrieval_profile import SYSTEM, SCHEMA, REASONING_EFFORT
from core.project_metadata import FINANCES, project_metadata, resolve_lineage
from core.project_similarity import compute_similarity
from core.search_cutoff import curve_elbow
from core.storage import now
from core.text import digest

VERSION = 'portfolio-graph-v7'
LENSES = ('balanced', 'profile', 'source')
_registry_lock = threading.Lock()
_leiden_lock = threading.Lock()


def graph_for(store):
    with _registry_lock:
        if not hasattr(store, '_project_graph'):
            store._project_graph = ProjectGraph(store)
        return store._project_graph


def ranked_neighbours(scores):
    return [[int(j) for j in np.argsort(-np.nan_to_num(row, nan=-np.inf), kind='stable')
             if j != i and np.isfinite(row[j])] for i, row in enumerate(scores)]


def retained_edges(scores, profile, source, neighbours, min_score):
    n = len(scores)
    neighbours = [set(row) for row in neighbours]
    result = []
    for i in range(n):
        for j in sorted(neighbours[i]):
            if j <= i or i not in neighbours[j]:
                continue
            # Conservative raw-channel floor; rank alone must not force weak links.
            floor = 0.35
            raw = [float(m[i, j]) for m in (profile, source) if np.isfinite(m[i, j])]
            if not raw or max(raw) < floor or scores[i, j] < min_score:
                continue
            result.append((i, j, float(scores[i, j])))
    return result


def sparse_edges(scores, profile, source, k=6, min_score=.35):
    return retained_edges(scores, profile, source,
                          [row[:k] for row in ranked_neighbours(scores)], min_score)


def connection_proximity(scores, profile, source, min_score):
    """Small per-node explanation of the first possible mutual fixed-k link.

    Check every above-floor pair, not just a project's highest score: another
    pair can become reciprocal sooner. Ranks use the same stable, full-corpus
    ordering as retained_edges, including candidates rejected by score floors.
    Export only O(n) results; the temporary integer rank matrix stays offline.
    """
    ranked = ranked_neighbours(scores)
    n = len(ranked)
    ranks = np.full((n, n), n + 1, dtype=np.int32)
    for i, row in enumerate(ranked):
        ranks[i, row] = np.arange(1, len(row) + 1)
    result = []
    for i, row in enumerate(ranked):
        candidates = np.asarray(row, dtype=np.int32)
        raw_ok = ((np.isfinite(profile[i, candidates]) & (profile[i, candidates] >= .35)) |
                  (np.isfinite(source[i, candidates]) & (source[i, candidates] >= .35)))
        candidates = candidates[(scores[i, candidates] >= min_score) & raw_ok]
        if not len(candidates):
            result.append({'minimum_neighbours': None})
            continue
        required = np.maximum(ranks[i, candidates], ranks[candidates, i])
        chosen = int(np.argmin(required))
        j = int(candidates[chosen])
        result.append({'minimum_neighbours': int(required[chosen]), 'candidate_index': j,
                       'rank': int(ranks[i, j]), 'reverse_rank': int(ranks[j, i])})
    return result


def connection_options(scores, profile, source, min_score):
    """Precompute fixed 4–10 and two cumulative, per-project elbow prefixes.

    Elbows use the complete compatible project ranking, not search's top-50
    window. No detected bend falls back to six; a missing second bend keeps
    the first prefix. Reciprocal selection and existing score floors still
    apply, so an elbow never manufactures a weak connection.
    """
    ranked = ranked_neighbours(scores)
    first_counts, second_counts, first_fallback, second_fallback = [], [], [], []
    for i, row in enumerate(ranked):
        values = [float(scores[i, j]) for j in row]
        first = curve_elbow(values)
        second = curve_elbow(values[first:]) if first is not None else None
        first_counts.append(first if first is not None else min(6, len(row)))
        second_counts.append(first + second if second is not None else first_counts[-1])
        first_fallback.append('six' if first is None else None)
        second_fallback.append('six' if first is None else 'first' if second is None else None)
    options = {}
    counts = {str(k): [min(k, len(row)) for row in ranked] for k in range(4, 11)}
    counts.update(first=first_counts, second=second_counts)
    for name, ends in counts.items():
        prefixes = [row[:end] for row, end in zip(ranked, ends)]
        options[name] = {'edges': retained_edges(scores, profile, source, prefixes, min_score),
                         'cutoff_counts': ends,
                         'fallbacks': first_fallback if name == 'first' else second_fallback if name == 'second' else [None] * len(ranked)}
    return options


def unlinked_layout(ids, diameters):
    """Seeded, size-aware scatter for projects without retained similarity links.

    Their relative positions carry no semantic meaning. A separate, irregular
    cloud keeps them discoverable without implying rows, columns or new edges.
    All spacing is calculated during preprocessing, never in the browser.
    """
    rng = np.random.default_rng(42)
    radii = diameters[ids] / 2 + 8.5
    radius = max(35, math.sqrt(float((radii * radii).sum()) / .5))
    result = np.zeros((len(ids), 2), dtype=float)
    placed = []
    # Give large expenditure glyphs room before filling the remaining gaps.
    for local in sorted(range(len(ids)), key=lambda i: (-diameters[ids[i]], ids[i])):
        while True:
            angle = rng.uniform(0, 2 * math.pi, 256)
            distance = radius * np.sqrt(rng.uniform(0, 1, 256))
            candidates = np.column_stack((np.cos(angle) * distance * 1.2,
                                          np.sin(angle) * distance / 1.2))
            if placed:
                delta = candidates[:, None, :] - result[placed][None, :, :]
                required = radii[local] + radii[placed]
                allowed = ((delta * delta).sum(axis=2) >= required * required).all(axis=1)
            else:
                allowed = np.ones(len(candidates), dtype=bool)
            if allowed.any():
                result[local] = candidates[np.flatnonzero(allowed)[0]]
                placed.append(local)
                break
            radius *= 1.12
    return result


def community_layout(nodes, edges):
    """Seeded ForceAtlas2; component packing and glyph collision pass happen offline."""
    n = len(nodes)
    graph = nx.Graph()
    graph.add_nodes_from(range(n))
    graph.add_weighted_edges_from(edges)
    components = sorted(nx.connected_components(graph), key=lambda c: (-len(c), min(c)))
    groups = list(range(n))
    if edges:
        with _leiden_lock:
            ig.set_random_number_generator(random.Random(42))
            igraph = ig.Graph(n=n, edges=[(a, b) for a, b, _ in edges])
            partition = igraph.community_leiden(objective_function='modularity', weights=[w for _, _, w in edges], n_iterations=-1)
            groups = partition.membership
    positions = np.zeros((n, 2), dtype=float)
    max_budget = max([node['money']['budget']['value'] or 0 for node in nodes] + [1])
    diameters = np.asarray([max(10, 72 * math.sqrt((node['money']['budget']['value'] or 0) / max_budget)) for node in nodes])
    islands = []
    for component in components:
        ids = sorted(component)
        if len(ids) == 1:
            islands.extend(ids)
            continue
        subgraph = graph.subgraph(ids)
        seed = {i: np.random.default_rng(i + 42).uniform(-1, 1, 2) for i in ids}
        local = nx.forceatlas2_layout(subgraph, pos=seed, max_iter=250, seed=42, gravity=1.0,
                                      node_mass={i: 1 for i in ids}, scaling_ratio=2.0, weight='weight')
        arr = np.asarray([local[i] for i in ids])
        arr -= arr.mean(axis=0)
        span = max(float(np.ptp(arr, axis=0).max()), 1e-9)
        arr *= max(150, math.sqrt(len(ids)) * 53) / span
        # Expenditure-independent forces, followed by a glyph collision pass.
        # Invisible hit padding keeps small projects individually pickable.
        # Chunk collision checks: avoid an N x N x 2 displacement tensor.
        radii = diameters[ids] / 2
        for iteration in range(100):
            movement = np.zeros_like(arr)
            collided = False
            for begin in range(0, len(ids), 128):
                end = min(begin + 128, len(ids))
                delta = arr[begin:end, None, :] - arr[None, :, :]
                distance = np.sqrt((delta * delta).sum(axis=2))
                distance[np.arange(end-begin), np.arange(begin,end)] = np.inf
                required = radii[begin:end,None] + radii[None,:] + 17
                if (distance < required).any():
                    collided = True
                push = np.maximum(required - distance, 0) / np.maximum(distance, .01) * .28
                movement[begin:end] = (delta * push[:,:,None]).sum(axis=1)
            if not collided:
                break
            arr += movement + np.random.default_rng(iteration + 42).normal(0,.03,arr.shape)
        # A landscape viewport is wider than it is tall. Preserve vertical grouping,
        # expand horizontal spacing, and avoid wasting half the canvas on blank margins.
        widths = np.ptp(arr, axis=0)
        arr[:, 0] *= max(1, 1.7 * widths[1] / max(widths[0], 1))
        islands.append((ids, arr))
    packs = [x for x in islands if isinstance(x, tuple)]
    isolated = [x for x in islands if isinstance(x, int)]
    if isolated:
        packs.append((isolated, unlinked_layout(isolated, diameters)))
    total = sum((np.ptp(a, axis=0)[0] + 100) * (np.ptp(a, axis=0)[1] + 100) for _, a in packs)
    row_limit = max(600, math.sqrt(total * 2.0), max([np.ptp(a, axis=0)[0] + 100 for _, a in packs] + [0]))
    x = y = row_height = 0.0
    for ids, arr in packs:
        arr -= arr.min(axis=0)
        width, height = np.ptp(arr, axis=0) + 100
        if x and x + width > row_limit:
            x = 0; y += row_height; row_height = 0
        for i, xy in zip(ids, arr):
            positions[i] = xy + [x + 50, y + 50]
        x += width; row_height = max(row_height, height)
    community_ids = sorted(set(groups), key=lambda g: min(i for i in range(n) if groups[i] == g))
    remap = {g: i for i, g in enumerate(community_ids)}
    group_info = []
    for g in community_ids:
        ids = [i for i in range(n) if groups[i] == g]
        tags = Counter(t for i in ids for t in nodes[i]['technology'])
        if len(ids) < 3:
            continue
        group_info.append({'id': remap[g], 'label': tags.most_common(1)[0][0] if tags else 'Mixed research',
                           'count': len(ids), 'x': float(positions[ids, 0].mean()), 'y': float(positions[ids, 1].min() - 65)})
    return {'positions': positions.round(2).tolist(), 'groups': [remap[g] for g in groups],
            'communities': group_info, 'components': len(components),
            'isolated': [i for i in range(n) if graph.degree(i) == 0]}


def lineage_positions(nodes, edges):
    graph = nx.DiGraph()
    graph.add_nodes_from(range(len(nodes)))
    lookup = {p['id']: i for i, p in enumerate(nodes)}
    graph.add_edges_from((lookup[e['source']], lookup[e['target']]) for e in edges)
    condensed = nx.condensation(graph)
    levels = {}
    for group in nx.topological_sort(condensed):
        levels[group] = max((levels[p] + 1 for p in condensed.predecessors(group)), default=0)
    positions = [None] * len(nodes)
    rows = Counter()
    cycles = []
    for group in sorted(condensed.nodes, key=lambda g: (not any(graph.degree(i) for i in condensed.nodes[g]['members']), levels[g], min(condensed.nodes[g]['members']))):
        members = sorted(condensed.nodes[group]['members'])
        if len(members) > 1:
            cycles.append([nodes[i]['id'] for i in members])
        level = levels[group]
        for i in members:
            positions[i] = [level * 320, rows[level] * 100]
            rows[level] += 1
    return positions, cycles


class ProjectGraph:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.signature = None
        self.bundle = None
        self.error = None
        self.cache_path = store.path.with_suffix('.project-map.npz')

    def revision(self):
        return digest(json.dumps([VERSION, EMBEDDING, DIMENSIONS, RECIPE,
            self.store.meta('search_revision'), self.store.meta('passage_vector_revision'),
            self.store.meta('graph_profile_revision'), self.store.meta('retrieval_term_overrides'),
            self.store.meta('last_successful_full_refresh_at'), digest(SYSTEM+REASONING_EFFORT+json.dumps(SCHEMA,sort_keys=True))], sort_keys=True))

    def warm_background(self):
        def run():
            try:
                self.get()
            except Exception as exc:
                self.error = str(exc)
        threading.Thread(target=run, daemon=True, name='portfolio-precompute').start()

    def get(self):
        with self.lock:
            signature = self.revision()
            if self.signature == signature and self.bundle is not None:
                return self.bundle
            if self.cache_path.exists():
                try:
                    with np.load(self.cache_path, allow_pickle=False) as saved:
                        metadata = json.loads(str(saved['metadata']))
                        if metadata['signature'] == signature:
                            self.bundle = {'public': metadata['public'], 'passages': metadata['passages'],
                                           'arrays': {key: saved[key] for key in saved.files if key != 'metadata'}}
                            self.signature = signature
                            return self.bundle
                except (OSError, ValueError, KeyError):
                    pass  # Partial/old caches never become an empty or incomplete catalogue.
            start = time.perf_counter()
            index = self.store.keyword_snapshot()
            projects = sorted(index.projects, key=lambda p: p['id'])
            nodes = [project_metadata(p) for p in projects]
            arrays, coverage, passages = compute_similarity(self.store, projects, index)
            for node, cover in zip(nodes, coverage):
                node['coverage'] = cover
            lineage = resolve_lineage(nodes)
            lenses = {}
            for lens in LENSES:
                options = connection_options(arrays[lens], arrays['profile'] if lens == 'balanced' else arrays[lens], arrays['source'] if lens == 'balanced' else arrays[lens], .85 if lens=='balanced' else .35)
                # One stable layout/grouping per lens; cutoff changes reveal edges,
                # rather than moving all projects and recomputing 27 force layouts.
                default = community_layout(nodes, options['6']['edges'])
                drawings = {}
                for name, option in options.items():
                    topology = nx.Graph()
                    topology.add_nodes_from(range(len(nodes)))
                    topology.add_edges_from((a,b) for a,b,_ in option['edges'])
                    drawings[name] = {**default, **option,
                                      'isolated': [i for i in range(len(nodes)) if topology.degree(i)==0],
                                      'components': nx.number_connected_components(topology),
                                      'edges': [[a,b,round(w,5)] for a,b,w in option['edges']]}
                lenses[lens] = {**drawings.pop('6'), 'variants': drawings}
            lineage_pos, cycles = lineage_positions(nodes, lineage)
            public = {'version': VERSION, 'revision': signature, 'built_at': now(),
                      'source_checked_at': self.store.meta('last_successful_full_refresh_at'),
                      'nodes': nodes, 'lenses': lenses, 'lineage': lineage, 'lineage_positions': lineage_pos,
                      'cycles': cycles, 'financial_measures': [{'id': k, 'label': label, 'available': sum(n['money'][k]['value'] is not None for n in nodes)} for k, (label, _, _) in FINANCES.items()],
                      'coverage': {'catalogue': len(nodes), 'profile': sum(c['profile'] for c in coverage),
                                   'source': sum(c['complete'] for c in coverage), 'passages': sum(c['passages'] for c in coverage),
                                   'passages_expected': sum(c['expected'] for c in coverage)},
                      'method': {'neighbours': 6, 'fixed_min': 4, 'fixed_max': 10,
                                 'elbow': 'Full per-project score curve; before first bend, then cumulative second bend; no first uses six, no second uses first',
                                 'raw_floor': .35, 'balanced_floor': .85,
                                 'source': 'Bidirectional best-passage average, balanced by source field',
                                 'layout': 'Weighted ForceAtlas2; stable positions and groups per lens across cutoffs; component packing is non-semantic',
                                 'communities': 'Leiden; source technology labels', 'api_calls': 0}}
            public['build_seconds'] = round(time.perf_counter() - start, 3)
            if self.revision() != signature:
                # Do not publish a mixture if an import/index finishes during preprocessing.
                return self.get()
            metadata = {'signature': signature, 'public': public, 'passages': passages}
            temporary = self.cache_path.with_suffix('.tmp-' + str(threading.get_ident()) + '.npz')
            try:
                np.savez_compressed(temporary, metadata=np.asarray(json.dumps(metadata)), **arrays)
                os.replace(temporary, self.cache_path)
            finally:
                temporary.unlink(missing_ok=True)
            self.bundle = {'public': public, 'arrays': arrays, 'passages': passages}
            self.signature = signature
            self.error = None
            return self.bundle

    def wire(self, bundle, compressed=False):
        """Serialize/compress a revision once, not on every browser request."""
        if '_json' not in bundle:
            bundle['_json'] = json.dumps(bundle['public'],separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
        if compressed:
            if '_gzip' not in bundle:
                bundle['_gzip'] = gzip.compress(bundle['_json'],compresslevel=6,mtime=0)
            return bundle['_gzip']
        return bundle['_json']

    def neighbours(self, id, lens='balanced'):
        bundle = self.get()
        nodes = bundle['public']['nodes']
        lookup = {p['id']: i for i, p in enumerate(nodes)}
        if id not in lookup:
            raise KeyError(id)
        i = lookup[id]
        result = []
        for j, node in enumerate(nodes):
            if i == j:
                continue
            scores = {key: float(bundle['arrays'][key][i, j]) if np.isfinite(bundle['arrays'][key][i, j]) else None for key in ('balanced', 'profile', 'source')}
            result.append({'id': node['id'], **scores})
        result.sort(key=lambda r: (r[lens] is not None, r[lens] or -1), reverse=True)
        return {'revision': bundle['public']['revision'], 'id': id, 'matches': result}

    def pair(self, a, b):
        bundle = self.get()
        nodes = bundle['public']['nodes']
        lookup = {p['id']: i for i, p in enumerate(nodes)}
        if a not in lookup or b not in lookup:
            raise KeyError(a if a not in lookup else b)
        if a == b:
            raise ValueError('Choose two different projects')
        i, j = lookup[a], lookup[b]
        scores = {key: float(bundle['arrays'][key][i, j]) if np.isfinite(bundle['arrays'][key][i, j]) else None for key in ('balanced', 'profile', 'source')}
        originals = {p['id']: p for p in self.store.passages(a) + self.store.passages(b)}
        evidence = []
        for aa, bb in bundle['arrays']['evidence'][i, j]:
            if aa < 0 or bb < 0:
                continue
            left, right = bundle['passages'][int(aa)], bundle['passages'][int(bb)]
            if left['source_id'] in originals and right['source_id'] in originals:
                evidence.append({'a': {**left, 'text': originals[left['source_id']]['text'][:1000]},
                                 'b': {**right, 'text': originals[right['source_id']]['text'][:1000]}})
        shared, different = {}, {}
        for field in ('technology', 'themes', 'research', 'funding'):
            left, right = set(nodes[i][field]), set(nodes[j][field])
            shared[field] = sorted(left & right)
            different[field] = {'a': sorted(left - right), 'b': sorted(right - left)}
        return {'revision': bundle['public']['revision'], 'a': a, 'b': b, 'scores': scores,
                'evidence': evidence, 'shared': shared, 'different': different}
