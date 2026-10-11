import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from core.map_export import export_map
from core.project_graph import graph_for
from core.project_similarity import compute_similarity
from core.passage_search import chunks
from core.config import DIMENSIONS
from tests import test_project_graph

class MapExportTests(unittest.TestCase):
    setUp = test_project_graph.GraphTests.setUp

    def test_static_rows_preserve_all_scores_and_original_evidence(self):
        with tempfile.TemporaryDirectory() as temp, patch('adapters.models.openai.OpenAI.call',side_effect=AssertionError('No paid calls')):
            path=Path(temp)
            result=export_map(self.store,path)
            manifest=json.loads((path/'manifest.json').read_text())
            engine=graph_for(self.store)
            self.assertEqual(result['entries'],4)
            self.assertEqual({n['id'] for n in manifest['nodes']},{p['id'] for p in self.store.projects()})
            self.assertTrue(all(not d['variants'] for d in manifest['lenses'].values()))
            self.assertEqual(set(manifest['connection_proximity']),{'balanced','profile','source'})
            self.assertTrue(all(len(rows)==4 for rows in manifest['connection_proximity'].values()))
            self.assertEqual(len(list(path.rglob('layouts/*/*.json'))),24)
            root=path/manifest['snapshot']['root']
            for i,node in enumerate(manifest['nodes']):
                raw=(root/'rows'/f'{i}.bin').read_bytes()
                self.assertEqual(len(raw),4*36)
                scores=np.frombuffer(raw[:4*12],dtype='<f4').reshape(4,3)
                evidence=np.frombuffer(raw[4*12:],dtype='<i4').reshape(4,3,2)
                left=json.loads((root/'projects'/f'{i}.json').read_text())
                for j,other in enumerate(manifest['nodes']):
                    if i==j:continue
                    pair=engine.pair(node['id'],other['id'])
                    for k,key in enumerate(('balanced','profile','source')):
                        if pair['scores'][key] is None:self.assertTrue(np.isnan(scores[j,k]))
                        else:self.assertAlmostEqual(scores[j,k],pair['scores'][key])
                    right=json.loads((root/'projects'/f'{j}.json').read_text())
                    restored=[{'a':left['passages'][str(a)],'b':right['passages'][str(b)]} for a,b in evidence[j] if a>=0 and b>=0]
                    self.assertEqual(len(restored),len(pair['evidence']))
                    for actual,expected in zip(restored,pair['evidence']):
                        for side in ('a','b'):
                            for key in ('text','field','source_id'):self.assertEqual(actual[side][key],expected[side][key])
            public_text=''.join(p.read_text() for p in path.rglob('*.json'))
            self.assertNotIn('PRIVATE GENERATED',public_text)
            self.assertNotIn('OPENAI_API_KEY',public_text)

    def test_cutoff_variants_keep_positions_and_groups_stable(self):
        public=graph_for(self.store).get()['public']
        for lens,drawing in public['lenses'].items():
            for variant in drawing['variants'].values():
                self.assertEqual(variant['positions'],drawing['positions'])
                self.assertEqual(variant['groups'],drawing['groups'])

    def test_network_roles_are_source_fields_not_inferred_from_owner(self):
        from core.project_metadata import project_metadata
        project=self.store.project('a')
        project['raw_fields']={'Collaborating Networks':['Partner A','Partner B'],'Lead Sector':'Electricity Distribution'}
        node=project_metadata(project)
        self.assertEqual(node['participants'],['Partner A','Partner B'])
        self.assertEqual(node['sector'],['Electricity Distribution'])
        project['raw_fields']={}
        self.assertEqual(project_metadata(project)['participants'],[])
        self.assertEqual(project_metadata(project)['sector'],[])

    def test_blocked_source_scores_equal_dense_reference_for_varied_vectors(self):
        index=self.store.keyword_snapshot()
        candidates=chunks(index.projects,index.passages)
        rng=np.random.default_rng(23)
        vectors={p['text']:rng.normal(size=DIMENSIONS).astype(np.float32) for p in candidates}
        self.store.save_passage_vectors([(text,vector.tolist()) for text,vector in vectors.items()])
        arrays,_,selected=compute_similarity(self.store,index.projects,index)
        matrix=np.asarray([vectors[p['text']]/np.linalg.norm(vectors[p['text']]) for p in candidates])
        dense=np.clip(np.einsum('ik,jk->ij',matrix,matrix,optimize=False),-1,1)
        for i,a in enumerate(index.projects):
            aa=[k for k,c in enumerate(candidates) if c['project_id']==a['id']]
            for j,b in enumerate(index.projects):
                if i==j:continue
                bb=[k for k,c in enumerate(candidates) if c['project_id']==b['id']]
                if not aa or not bb:continue
                block=dense[np.ix_(aa,bb)]
                from collections import Counter
                ac=Counter(candidates[k]['field'] for k in aa);bc=Counter(candidates[k]['field'] for k in bb)
                expected=(np.average(block.max(axis=1),weights=[1/ac[candidates[k]['field']] for k in aa])+np.average(block.max(axis=0),weights=[1/bc[candidates[k]['field']] for k in bb]))/2
                self.assertAlmostEqual(float(arrays['source'][i,j]),float(expected),places=6)

if __name__=='__main__':unittest.main()
