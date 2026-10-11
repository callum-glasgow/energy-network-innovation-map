import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from datetime import datetime
from adapters.ena.downloads import import_download, read_rows, download, FIELD_MAP
from core.config import DIMENSIONS, OWNERS, ROOT
from core.storage import Store
from core.passage_search import chunks
from core.map_export import export_map
from scripts.map_release import write_checksums, validate_site, sha256, source_fingerprint
from scripts.update_map import update, coverage, revisions, promote_database, copy_database
from tests.fixtures import project

VECTOR = [1.] + [0.]*(DIMENSIONS-1)


def fake_build(destination, database, archive, report, compatibility):
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'assets').mkdir(exist_ok=True)
    (destination/'assets/app.js').write_text('console.log("fixture")')
    (destination/'index.html').write_text('<script src="./assets/app.js"></script>')
    (destination/'.nojekyll').write_text('')
    for name in ('serve.py','Start map.command','Start map.bat','README.txt'):
        shutil.copy2(ROOT/'map-package'/name, destination/name)
    exported=export_map(Store(database), destination/'data')
    (destination/'build-info.json').write_text(json.dumps({'revision':exported['revision'],'source_fingerprint':source_fingerprint(ROOT)}))
    write_checksums(destination)
    result=validate_site(destination)
    with zipfile.ZipFile(archive,'w') as package:
        for path in destination.rglob('*'):
            if path.is_file():package.write(path, Path('energy-network-map')/path.relative_to(destination))
    result['archive_sha256']=sha256(archive)
    report.write_text(json.dumps(result))
    return result


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.store=Store(self.root/'live.sqlite3')
        self.store.upsert([project()])
        self.seed(self.store)
        self.source=self.root/'export.json'
        self.site=self.root/'map';self.site.mkdir();(self.site/'previous.txt').write_text('last good site')
        self.archive=self.root/'map.zip';self.archive.write_bytes(b'last good archive')

    def seed(self, store):
        for p in store.projects():
            store.save_summary(p, {'summary':'Cached '+p['id']})
            store.save_vector(p['title']+'\nCached '+p['id'], VECTOR)
        index=store.keyword_snapshot()
        store.save_passage_vectors([(p['text'],VECTOR) for p in chunks(index.projects,index.passages)])

    def run_update(self, rows, **kwargs):
        if rows is not None:self.source.write_text(json.dumps(rows))
        return update(self.source, database=self.store.path, site=self.site, archive=self.archive,
                      builder=fake_build, work_dir=self.root/'jobs', **kwargs)

    def test_partial_import_preserves_fields_and_explicit_blanks_clear(self):
        old=self.store.projects()
        rows=[{'GUID':'p1','Project Title':old[0]['title'],'Owner Network':OWNERS[0],
               'Project Status':'Complete','Project Budget':'£40k','Project End Date':'10/10/2026'}]
        records,report=import_download(rows,old)
        self.assertFalse(report['errors']);self.assertEqual(records[0]['reference'],old[0]['reference'])
        self.assertEqual(records[0]['fields'],old[0]['fields']);self.assertEqual(records[0]['budget'],40000)
        self.assertEqual(records[0]['end_date'],'2026-10-10')
        rows[0]['Summary']=''
        records,_=import_download(rows,old);self.assertEqual(records[0]['fields'],{})

    def test_identity_resolution_and_ambiguity(self):
        row={'Project Title':'New','Project Reference Number':'R','Owner Network':OWNERS[0]}
        cat=[{'Key':'guid','OwnerNetwork':OWNERS[0],'ProjectReferenceNumber':'R'}]
        records,report=import_download([row],[],catalogue_rows={'Results':cat})
        self.assertFalse(report['errors']);self.assertEqual(records[0]['id'],'guid')
        _,report=import_download([row],[],catalogue_rows=cat+[dict(cat[0],Key='other')])
        self.assertIn('unique ENA GUID',report['errors'][0]['error'])
        _,report=import_download([dict(row,GUID='a')]*2,[])
        self.assertIn('Duplicate',report['errors'][0]['error'])

    def test_csv_and_xlsx_preserve_narrative_and_typed_dates(self):
        csv=self.root/'export.csv'
        csv.write_text('\ufeffGUID,Project Title,Owner Network,Summary,Project Budget\na,A,'+OWNERS[0]+',"First line\nSecond line","£1,234.50"\n')
        records,report=import_download(read_rows(csv),[])
        self.assertFalse(report['errors']);self.assertEqual(records[0]['fields']['summary'],'First line Second line')
        self.assertEqual(records[0]['budget'],1234.5)
        from openpyxl import Workbook
        workbook=Workbook(); sheet=workbook.active
        sheet.append(['GUID','Project Title','Owner Network','Project Start Date','Project End Date'])
        sheet.append(['a','A',OWNERS[0],datetime(2026,1,2),datetime(2026,8,3)])
        xlsx=self.root/'export.xlsx';workbook.save(xlsx);workbook.close()
        records,report=import_download(read_rows(xlsx),[])
        self.assertFalse(report['errors']);self.assertEqual(records[0]['start_date'],'2026-01-02')

    def test_bad_date_blocks_entire_import_and_does_not_change_live(self):
        baseline=revisions(self.store)
        with self.assertRaisesRegex(ValueError,'Invalid Project End Date'):
            self.run_update([dict(project(),end_date='31/02/2026')],apply=True)
        self.assertEqual(revisions(self.store),baseline);self.assertTrue((self.site/'previous.txt').exists())

    def test_unchanged_profiles_reused_and_preview_makes_no_calls(self):
        with patch('adapters.models.openai.OpenAI.call',side_effect=AssertionError('Paid call')):
            result=self.run_update(self.store.projects())
        self.assertEqual(result['pending']['luna_profiles'],0)
        self.assertEqual(result['pending']['profile_embeddings'],0)
        self.assertEqual(result['pending']['original_passage_embeddings'],0)
        self.assertEqual(result['paid_calls_made'],0)
        self.assertTrue((self.site/'previous.txt').exists())

    def test_taxonomy_labels_with_commas_keep_original_export_and_profile_cache(self):
        p=self.store.project('p1')
        p['raw_fields']={'Research Areas':'ED - Safety, health and environment'}
        self.store.upsert([p]);p=self.store.project('p1');self.seed(self.store)
        incoming=copy.deepcopy(p);incoming['research']=['ED - Safety, health and environment']
        records,report=import_download([incoming],[p])
        self.assertFalse(report['errors'])
        self.assertEqual(records[0]['raw_fields']['Research Areas'],p['raw_fields']['Research Areas'])
        self.assertEqual(records[0]['research'],incoming['research'])
        self.store.upsert(records)
        self.assertEqual(coverage(self.store)['luna_profiles'],[])

    def test_new_entry_is_indexed_without_regenerating_existing_entry(self):
        new=project('new','NEW_1','New cable monitoring','Cable insulation monitoring and fault detection.')
        class Model:
            def embedding(self,*args):return VECTOR
        with patch('core.retrieval_profile.generate_summary',return_value={'summary':'Cable insulation facts'}) as generate:
            result=self.run_update([self.store.project('p1'),new],apply=True,live=True,model=Model())
        self.assertEqual(generate.call_count,1);self.assertEqual(result['changes']['new'],1)
        self.assertEqual(validate_site(self.site)['entries'],2)
        self.assertEqual(self.store.summary(self.store.project('p1'))['summary'],'Cached p1')

    def test_fresh_database_preview_does_not_create_live_files(self):
        missing=self.root/'fresh/database.sqlite3';self.source.write_text(json.dumps([project()]))
        with patch('adapters.models.openai.OpenAI.call',side_effect=AssertionError('Paid call')):
            result=update(self.source,database=missing)
        self.assertEqual(result['changes']['new'],1)
        self.assertFalse(missing.exists());self.assertFalse(missing.parent.exists())

    def test_identical_project_texts_keep_distinct_passage_identity_in_summary_cache(self):
        self.store.upsert([project('other')])
        first=self.store.project('p1');other=self.store.project('other')
        self.assertNotEqual(self.store.summary_key(first),self.store.summary_key(other))
        self.store.save_summary(other,{'summary':'Separate profile'})
        self.assertEqual(self.store.summary(first)['summary'],'Cached p1')

    def test_metadata_only_updates_publish_locally_without_model_calls(self):
        p=self.store.project('p1');p['status']='Complete';p['end_date']='2026-10-10'
        with patch('adapters.models.openai.OpenAI.call',side_effect=AssertionError('Paid call')):
            result=self.run_update([p],apply=True)
        self.assertEqual(result['phase'],'complete');self.assertEqual(self.store.project('p1')['status'],'Complete')
        self.assertEqual(validate_site(self.site)['entries'],1)
        self.assertTrue(Path(result['backup']).exists())

    def test_changed_narrative_requires_explicit_live_and_resumes_after_failure(self):
        p=self.store.project('p1');p['fields']['summary']='New transformer monitoring methods.'
        baseline=revisions(self.store)
        with self.assertRaisesRegex(ValueError,'Missing model outputs'):
            self.run_update([p],apply=True)
        self.assertEqual(revisions(self.store),baseline)
        class Fail:
            def embedding(self,*args):raise ValueError('Temporary embedding failure')
        with patch('core.retrieval_profile.generate_summary', return_value={'summary':'New transformer facts'}) as generate:
            with self.assertRaisesRegex(ValueError,'Temporary embedding failure'):
                self.run_update(None,apply=True,live=True,model=Fail())
            self.assertEqual(generate.call_count,1)
        self.assertEqual(self.store.project('p1')['fields']['summary'],project()['fields']['summary'])
        self.assertEqual(self.archive.read_bytes(),b'last good archive')
        class Model:
            calls=0
            def embedding(self,*args):self.calls+=1;return VECTOR
        model=Model()
        with patch('core.retrieval_profile.generate_summary',side_effect=AssertionError('Must reuse saved Luna output')):
            result=self.run_update(None,apply=True,live=True,model=model)
        self.assertEqual(result['phase'],'complete');self.assertGreater(model.calls,0)
        self.assertEqual(self.store.project('p1')['fields']['summary'],p['fields']['summary'])
        self.assertEqual(coverage(self.store)['luna_profiles'],[])

    def test_merge_keeps_missing_and_replace_is_scoped(self):
        outside=project('outside');outside['owner']='Other energy network'
        self.store.upsert([project('missing'),outside]);self.seed(self.store)
        p=self.store.project('p1')
        preview=self.run_update([p]);self.assertEqual(preview['changes']['retained'],2)
        result=self.run_update([p],replace=True,apply=True)
        self.assertEqual({p['id'] for p in self.store.projects()},{'p1','outside'})
        self.assertEqual(result['changes']['deactivated'],1)
        records,report=import_download([outside],[],scope='all')
        self.assertFalse(report['errors']);self.assertEqual(len(records),1)

    def test_concurrent_report_and_query_cache_preserved_and_source_change_rejected(self):
        staged=self.root/'prepared.sqlite3';copy_database(self.store.path,staged);stage=Store(staged)
        baseline=revisions(self.store)
        p=stage.project('p1');p['status']='Complete';stage.upsert([p])
        with self.store.connect() as connection:connection.execute('INSERT INTO reports VALUES (?,?)',('new','{}'))
        self.store.save_vector('query during update',VECTOR)
        promote_database(self.store,stage,baseline)
        with self.store.connect() as connection:self.assertEqual(connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0],1)
        self.assertIsNotNone(self.store.vector('query during update'))
        baseline=revisions(self.store);self.store.upsert([project('new')])
        with self.assertRaisesRegex(ValueError,'changed during this update'):
            promote_database(self.store,stage,baseline)
        self.assertIsNotNone(self.store.project('new'))

    def test_recovery_if_process_stops_after_database_commit(self):
        from scripts import update_map
        original=update_map.promote_database
        def crash(*args):original(*args);raise RuntimeError('Process stopped')
        p=self.store.project('p1');p['status']='Complete'
        with patch.object(update_map,'promote_database',side_effect=crash):
            with self.assertRaisesRegex(RuntimeError,'Process stopped'):self.run_update([p],apply=True)
        self.assertEqual(self.store.project('p1')['status'],'Complete')
        self.assertTrue((self.site/'previous.txt').exists())
        result=self.run_update(None,apply=True)
        self.assertEqual(result['phase'],'complete');self.assertEqual(validate_site(self.site)['entries'],1)

    def test_build_failure_keeps_live_data_and_map(self):
        p=self.store.project('p1');p['status']='Complete';self.source.write_text(json.dumps([p]))
        def fail(**kwargs):raise ValueError('Build failed')
        with self.assertRaisesRegex(ValueError,'Build failed'):
            update(self.source,database=self.store.path,apply=True,work_dir=self.root/'jobs',builder=fail,site=self.site,archive=self.archive)
        self.assertEqual(self.store.project('p1')['status'],'Live')
        self.assertTrue((self.site/'previous.txt').exists())

    def test_downloader_keeps_guid_for_shared_reference_and_all_networks(self):
        cat={'Results':[{'Key':str(i),'Name':'Title '+str(i),'ProjectReferenceNumber':'SHARED',
                        'OwnerNetwork':OWNERS[0] if i==0 else 'Other network','Url':'/projects/'+str(i)} for i in range(2)]}
        def exported(rows,mapping):
            return ([{'Project Title':r['Name'],'Project Reference Number':'SHARED','Summary':'Narrative.'} for r in rows],b'')
        with patch('adapters.ena.downloads.catalogue',return_value=cat),patch('adapters.ena.downloads.request',return_value=json.dumps(FIELD_MAP).encode()),patch('adapters.ena.downloads.export_rows',side_effect=exported),patch('time.sleep'):
            result=download('all')
        self.assertEqual({p['id'] for p in result['projects']},{'0','1'})
        self.assertEqual(result['projects'][1]['owner'],'Other network')

if __name__=='__main__':unittest.main()
