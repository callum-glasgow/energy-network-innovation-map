"""Export a public, API-free map snapshot. No models, credentials or search assets."""
import copy
import json
from collections import defaultdict
from pathlib import Path
import numpy as np
from core.project_graph import connection_proximity, graph_for
from core.map_review import review_pack


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False), encoding='utf-8')


def export_map(store, destination):
    destination = Path(destination)
    bundle = graph_for(store).get()
    public = copy.deepcopy(bundle['public'])
    revision = public['revision']
    root = destination / revision
    root.mkdir(parents=True, exist_ok=True)
    n = len(public['nodes'])
    owners = sorted({p['owner'] for p in public['nodes']})
    arrays = bundle['arrays']
    public['connection_proximity'] = {
        lens: connection_proximity(arrays[lens], arrays['profile'] if lens == 'balanced' else arrays[lens],
                                   arrays['source'] if lens == 'balanced' else arrays[lens],
                                   public['method']['balanced_floor'] if lens == 'balanced' else public['method']['raw_floor'])
        for lens in public['lenses']}
    public['snapshot'] = {'format': 1, 'root': revision + '/', 'scope': ', '.join(owners),
                          'owners': owners, 'target_entries': 3200, 'row_bytes': n * 36,
                          'license_url': 'https://smarter.energynetworks.org/licenses/'}
    for lens, drawing in public['lenses'].items():
        for key, variant in drawing.pop('variants').items():
            write_json(root / 'layouts' / lens / (key + '.json'), variant)
        drawing['variants'] = {}
    # A row contains all scores and evidence IDs for its selected project. Browsers
    # fetch one row, never the dense corpus matrices or any embedding/profile text.
    rows = root / 'rows'
    rows.mkdir(exist_ok=True)
    detail_passages = defaultdict(dict)
    original_by_project = {}
    for i, node in enumerate(public['nodes']):
        original_by_project[node['id']] = {p['id']: p for p in store.passages(node['id'])}
        scores = np.column_stack([bundle['arrays'][key][i] for key in ('balanced','profile','source')]).astype('<f4')
        evidence = bundle['arrays']['evidence'][i].astype('<i4')
        (rows / (str(i) + '.bin')).write_bytes(scores.tobytes() + evidence.tobytes())
    for i, passage in enumerate(bundle['passages']):
        original = original_by_project[passage['project_id']].get(passage['source_id'])
        if original:
            detail_passages[passage['project_id']][str(i)] = {
                'field': passage['field'], 'source_id': passage['source_id'],
                'text': original['text'][:1000]}
    for i, node in enumerate(public['nodes']):
        project = store.project(node['id'])
        write_json(root / 'projects' / (str(i) + '.json'), {
            'revision': revision, 'id': node['id'], 'fields': project.get('fields', {}),
            'passages': detail_passages[node['id']]})
    write_json(destination / 'review-pack.json', review_pack(graph_for(store), bundle))
    # Publish pointer last. Old immutable revisions can remain usable during a rebuild.
    write_json(destination / 'manifest.json', public)
    return {'revision': revision, 'entries': n, 'scope': owners,
            'data_bytes': sum(p.stat().st_size for p in destination.rglob('*') if p.is_file()),
            'pair_row_bytes': n * 36, 'projected_3200_pair_bytes': 3200 * 3200 * 36}
