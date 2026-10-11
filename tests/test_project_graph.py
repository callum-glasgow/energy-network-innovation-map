import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core.config import DIMENSIONS
from core.passage_search import chunks
from core.project_graph import ProjectGraph, connection_options, connection_proximity, graph_for, sparse_edges
from core.project_metadata import amount, iso_date, project_metadata, resolve_lineage
from core.project_similarity import percentile_scores
from core.storage import Store
from tests.fixtures import project


class MetadataTests(unittest.TestCase):
    def test_money_never_concatenates_narrative_amounts(self):
        for raw, expected in [('£1,234.50',1234.5),('£90k',90000),('GBP 1.2 million',1200000),('0',0),('2.7m',2700000)]:
            self.assertEqual(amount(raw),expected)
        for raw in ['£90k plus £385k', 'Budget £30k, now £50k', '-100',float('inf'),True,'unknown']:
            self.assertIsNone(amount(raw))
    def test_dates_are_valid_uk_or_iso(self):
        self.assertEqual(iso_date('10/11/2026'),'2026-11-10')
        self.assertEqual(iso_date('2026-10-10T00:00:00Z'),'2026-10-10')
        self.assertIsNone(iso_date('31/02/2026'))
    def test_metadata_does_not_infer_missing_or_convert_budget_into_expenditure(self):
        p=project();p['raw_fields']={'Project Budget':'£40k','Preceding Projects':'R1, R2','Project Status':'Complete'}
        node=project_metadata(p)
        self.assertEqual(node['status'],'Complete')
        self.assertEqual(node['money']['budget']['value'],40000)
        self.assertIsNone(node['money']['nia']['value'])
        self.assertEqual(node['research'],[])
        self.assertEqual([r['reference'] for r in node['preceding']],['R1','R2'])
    def test_lineage_guid_identity_and_ambiguous_references(self):
        nodes=[project_metadata(project('a','SAME')),project_metadata(project('b','SAME')),project_metadata(project('c','R3'))]
        nodes[2]['preceding']=[{'reference':'SAME','field':'precedingProjects'},{'reference':'OTHER','field':'precedingProjects'},{'reference':'R3','field':'precedingProjects'}]
        edges=resolve_lineage(nodes)
        self.assertEqual(edges,[])
        self.assertEqual([r['state'] for r in nodes[2]['preceding']],['ambiguous','outside','self-link'])


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'projects.sqlite3')
        ps=[project('a','SAME','Overhead vegetation forecasting'),project('b','SAME','Overhead tree monitoring'),project('c','R3','Battery storage'),project('missing','R4','Sparse project','')]
        ps[1]['raw_fields']={'Preceding Projects':'R3'}
        self.store.upsert(ps)
        vector=[1.0]+[0.]*(DIMENSIONS-1)
        for p in self.store.projects():
            if p['id']=='missing':continue
            text='PRIVATE GENERATED PROFILE '+p['id']
            self.store.save_summary(p,{'summary':text})
            self.store.save_vector(p['title']+'\n'+text,vector)
        index=self.store.keyword_snapshot()
        self.store.save_passage_vectors([(c['text'],vector) for c in chunks(index.projects,index.passages)])
    def test_complete_node_coverage_missing_vectors_and_duplicate_refs(self):
        with patch('adapters.models.openai.OpenAI.call',side_effect=AssertionError('Paid call')):
            bundle=graph_for(self.store).get()
        public=bundle['public'];self.assertEqual({p['id'] for p in public['nodes']},{'a','b','c','missing'})
        self.assertEqual(public['coverage']['catalogue'],4)
        self.assertNotIn('PRIVATE GENERATED',json.dumps(public))
        self.assertNotIn('vector',json.dumps(public))
        missing=next(i for i,p in enumerate(public['nodes']) if p['id']=='missing')
        for lens,data in public['lenses'].items():
            self.assertEqual(len(data['positions']),4)
            self.assertTrue(np.isfinite(data['positions']).all())
            self.assertEqual(len({tuple(x) for x in data['positions']}),4)
            self.assertFalse(any(missing in edge[:2] for edge in data['edges']))
        self.assertEqual(public['lineage'][0]['source'],'c')
        self.assertEqual(public['lineage'][0]['target'],'b')
        for key in ('profile','source','balanced'):
            matrix=bundle['arrays'][key]
            self.assertTrue(np.allclose(matrix,matrix.T,equal_nan=True))
            self.assertTrue(np.isnan(np.diag(matrix)).all())
    def test_disk_cache_reused_and_invalidated_by_metadata(self):
        first=ProjectGraph(self.store).get()
        with patch('core.project_graph.compute_similarity',side_effect=AssertionError('Must reuse disk')):
            second=ProjectGraph(self.store).get()
        self.assertEqual(first['public']['revision'],second['public']['revision'])
        p=self.store.project('a');p['raw_fields']={'Funding Mechanism':'New source category'};self.store.upsert([p])
        third=graph_for(self.store).get()
        self.assertNotEqual(third['public']['revision'],second['public']['revision'])
        self.assertEqual(next(n for n in third['public']['nodes'] if n['id']=='a')['funding'],['New source category'])
    def test_query_embedding_does_not_rebuild_but_profile_vector_does(self):
        engine=graph_for(self.store);first=engine.get()['public']['revision']
        self.store.save_vector('new query',[1.]+[0.]*(DIMENSIONS-1))
        self.assertEqual(first,engine.get()['public']['revision'])
        p=self.store.project('a');s=self.store.summary_text(p)
        self.store.save_vector(p['title']+'\n'+s,[0.,1.]+[0.]*(DIMENSIONS-2))
        self.assertNotEqual(first,engine.get()['public']['revision'])
    def test_source_change_excludes_stale_vectors_without_losing_node(self):
        old=graph_for(self.store).get()['public']['revision']
        p=self.store.project('a');p['fields']['summary']='Completely changed source narrative';self.store.upsert([p])
        bundle=graph_for(self.store).get();node=next(n for n in bundle['public']['nodes'] if n['id']=='a')
        self.assertFalse(node['coverage']['profile']);self.assertFalse(node['coverage']['complete'])
        self.assertEqual(len(bundle['public']['nodes']),4)
        self.assertNotEqual(old,bundle['public']['revision'])
    def test_pair_evidence_is_original_and_reversible(self):
        engine=graph_for(self.store);a=engine.pair('a','b');b=engine.pair('b','a')
        self.assertEqual(a['scores'],b['scores'])
        for evidence in a['evidence']:
            for side,pid in [('a','a'),('b','b')]:
                original=next(p for p in self.store.passages(pid) if p['id']==evidence[side]['source_id'])
                self.assertIn(evidence[side]['text'],original['text'])
        self.assertNotIn('PRIVATE GENERATED',json.dumps(a))
        with self.assertRaises(ValueError):engine.pair('a','a')
        with self.assertRaises(KeyError):engine.pair('a','unknown')
    def test_empty_catalogue_and_single_node_remain_valid(self):
        empty=Store(Path(self.temp.name)/'empty.sqlite3');graph=ProjectGraph(empty).get()['public']
        self.assertEqual(graph['nodes'],[])
        empty.upsert([project()]);graph=graph_for(empty).get()['public']
        self.assertEqual(len(graph['nodes']),1)
        self.assertEqual(graph['lenses']['balanced']['positions'],[[50.,50.]])
    def test_mutual_links_are_bounded_and_no_forced_weak_links(self):
        rng=np.random.default_rng(42);a=rng.uniform(.4,1,(30,30));a=(a+a.T)/2;np.fill_diagonal(a,np.nan)
        edges=sparse_edges(a,a,a,k=6)
        degree=[sum(i in e[:2] for e in edges) for i in range(30)]
        self.assertLessEqual(max(degree),6)
        self.assertEqual(sparse_edges(a*.1,a*.1,a*.1),[])
    def test_first_link_can_use_a_different_pair_than_highest_score(self):
        scores=np.array([[np.nan,.9,.8,.1],[.9,np.nan,.99,.98],[.8,.99,np.nan,.7],[.1,.98,.7,np.nan]])
        result=connection_proximity(scores,scores,scores,.35)
        self.assertEqual(result[0],{'minimum_neighbours':2,'candidate_index':2,'rank':2,'reverse_rank':2})
        self.assertEqual(connection_proximity(scores,scores,scores,.85)[0]['minimum_neighbours'],3)
        self.assertTrue(all(r['minimum_neighbours'] is None for r in connection_proximity(scores,scores*.1,scores*.1,.35)))
    def test_first_link_rank_agrees_with_retained_graph_at_every_setting(self):
        rng=np.random.default_rng(12);scores=rng.uniform(.1,1,(18,18));scores=(scores+scores.T)/2
        np.fill_diagonal(scores,np.nan);scores[-1,:]=scores[:,-1]=np.nan
        proximity=connection_proximity(scores,scores,scores,.6)
        for k in range(1,len(scores)):
            linked={i for a,b,_ in sparse_edges(scores,scores,scores,k=k,min_score=.6) for i in (a,b)}
            expected={i for i,p in enumerate(proximity) if p['minimum_neighbours'] is not None and p['minimum_neighbours']<=k}
            self.assertEqual(linked,expected)
        self.assertIsNone(proximity[-1]['minimum_neighbours'])
    def test_percentiles_ties_symmetric_and_do_not_become_probability(self):
        a=np.array([[np.nan,.4,.8],[.4,np.nan,.8],[.8,.8,np.nan]])
        result=percentile_scores(a)
        self.assertTrue(np.allclose(result,result.T,equal_nan=True))
        self.assertAlmostEqual(result[0,1],1/6)
        self.assertAlmostEqual(result[0,2],2/3)

    def test_link_choices_preserve_fixed_default_and_cumulative_elbows(self):
        scores=np.full((13,13),.5);np.fill_diagonal(scores,np.nan)
        scores[0,1:]=np.array([100,98,50,49,48,47,10,9,8,7,6,5])/100
        scores[1:,0]=scores[0,1:]
        options=connection_options(scores,scores,scores,.35)
        self.assertEqual(set(options),{'4','5','6','7','8','9','10','first','second'})
        self.assertEqual(options['6']['edges'],sparse_edges(scores,scores,scores))
        self.assertEqual(options['first']['cutoff_counts'][0],2)
        self.assertEqual(options['second']['cutoff_counts'][0],6)
        self.assertLessEqual({e[:2] for e in options['first']['edges']},{e[:2] for e in options['second']['edges']})
        for k in range(4,11):
            self.assertLessEqual(max(sum(i in e[:2] for e in options[str(k)]['edges']) for i in range(13)),k)
        for option in options.values():
            self.assertFalse(any(a==b or w<.35 for a,b,w in option['edges']))

    def test_flat_missing_and_single_elbow_have_explicit_fallbacks(self):
        flat=np.full((8,8),.8);np.fill_diagonal(flat,np.nan)
        options=connection_options(flat,flat,flat,.35)
        self.assertEqual(options['first']['cutoff_counts'],[6]*8)
        self.assertEqual(options['second']['fallbacks'],['six']*8)
        missing=np.full((1,1),np.nan)
        options=connection_options(missing,missing,missing,.35)
        self.assertTrue(all(not opt['edges'] and opt['cutoff_counts']==[0] for opt in options.values()))
        scores=np.full((8,8),.8);np.fill_diagonal(scores,np.nan)
        scores[0,1:]=[1,1,1,.4,.4,.4,.4];scores[1:,0]=scores[0,1:]
        options=connection_options(scores,scores,scores,.35)
        self.assertEqual(options['second']['cutoff_counts'][0],3)
        self.assertEqual(options['second']['fallbacks'][0],'first')


if __name__=='__main__':unittest.main()
