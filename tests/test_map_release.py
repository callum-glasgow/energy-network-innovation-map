import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from scripts.map_release import extract_release, validate_site, write_checksums
from scripts.publish_map import publish
from scripts.build_map import build
from tests.test_map_updates import fake_build
from tests import test_project_graph


class ReleaseTests(unittest.TestCase):
    setUp = test_project_graph.GraphTests.setUp

    def package(self):
        folder=Path(self.temp.name)
        site=folder/'site';archive=folder/'energy-network-map.zip'
        fake_build(site,self.store.path,archive,folder/'report.json',False)
        return site,archive

    def test_portable_release_checks_exact_files_and_rejects_damage(self):
        site,archive=self.package()
        target=Path(self.temp.name)/'extracted'
        self.assertEqual(extract_release(archive,target)['entries'],4)
        (target/'assets/app.js').write_text('corrupted')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):validate_site(target)
        (site/'credentials.env').write_text('not for public release');write_checksums(site)
        with self.assertRaisesRegex(ValueError,'Unexpected file'):validate_site(site)

    def test_zip_rejects_escape_symlinks_and_normalized_duplicates(self):
        folder=Path(self.temp.name)
        for number,names in enumerate([['energy-network-map/../escape.txt'],['/energy-network-map/file.txt'],
                                      ['energy-network-map/a.txt','energy-network-map/./a.txt']]):
            archive=folder/f'bad{number}.zip'
            with zipfile.ZipFile(archive,'w') as package:
                for name in names:package.writestr(name,'x')
            with self.assertRaisesRegex(ValueError,'Unsafe'):extract_release(archive,folder/f'out{number}')
        archive=folder/'symlink.zip'
        with zipfile.ZipFile(archive,'w') as package:
            entry=zipfile.ZipInfo('energy-network-map/link.txt');entry.external_attr=(stat.S_IFLNK|0o777)<<16
            package.writestr(entry,'/etc/passwd')
        with self.assertRaisesRegex(ValueError,'Unsafe'):extract_release(archive,folder/'link-out')

    def test_truncated_row_detected_even_with_recomputed_checksums(self):
        site,_=self.package();manifest=json.loads((site/'data/manifest.json').read_text())
        (site/'data'/manifest['snapshot']['root']/'rows/0.bin').write_bytes(b'')
        write_checksums(site)
        with self.assertRaisesRegex(ValueError,'truncated'):validate_site(site)

    def test_publisher_preview_does_not_call_git_or_github(self):
        _,archive=self.package()
        with patch('scripts.publish_map.command',side_effect=AssertionError('Network or git call')):
            result=publish(archive,repo='example/energy-projects')
        self.assertFalse(result['published']);self.assertEqual(result['entries'],4)

    def test_publisher_requires_clean_pushed_source_and_uses_notes_file(self):
        _,archive=self.package()
        with patch('scripts.publish_map.command',return_value=' M README.md'):
            with self.assertRaisesRegex(ValueError,'Commit'):publish(archive,repo='example/energy-projects',execute=True)
        calls=[]
        def command(args,**kwargs):
            calls.append(args)
            if args[:2]==['git','rev-parse']:return 'abc123'
            if args[:2]==['gh','api'] and 'matching-refs' in args[2]:return '[]'
            if args[:3]==['gh','release','create']:
                self.assertIn('Source commit: abc123',Path(args[args.index('--notes-file')+1]).read_text())
                return 'https://github.com/example/energy-projects/releases/tag/'+args[3]
            return ''
        with patch('scripts.publish_map.command',side_effect=command):
            self.assertTrue(publish(archive,repo='example/energy-projects',execute=True)['published'])
        self.assertEqual(calls[2],['gh','api','repos/example/energy-projects/commits/abc123','--silent'])

    def test_publisher_blocks_existing_tags_and_stale_source(self):
        _,archive=self.package()
        with patch('scripts.map_release.source_fingerprint',return_value='0'*64):
            with self.assertRaisesRegex(ValueError,'source differs'):publish(archive,repo='example/energy-projects')
        def command(args,**kwargs):
            if args[:2]==['git','rev-parse']:return 'abc123'
            if args[:2]==['gh','api'] and 'matching-refs' in args[2]:
                return json.dumps([{'ref':'refs/tags/map-existing'}])
            if args[:3]==['gh','release','create']:raise AssertionError('Must not publish')
            return ''
        with patch('scripts.publish_map.command',side_effect=command):
            with self.assertRaisesRegex(ValueError,'already exists'):publish(archive,repo='example/energy-projects',tag='map-existing',execute=True)

    def test_build_failure_preserves_previous_site_and_zip(self):
        folder=Path(self.temp.name);target=folder/'current';target.mkdir();(target/'old.txt').write_text('keep')
        archive=folder/'current.zip';archive.write_bytes(b'keep')
        with patch('scripts.build_map.subprocess.run',side_effect=ValueError('Compiler failed')):
            with self.assertRaisesRegex(ValueError,'Compiler failed'):build(target,self.store.path,archive,folder/'build.json',False)
        self.assertEqual((target/'old.txt').read_text(),'keep');self.assertEqual(archive.read_bytes(),b'keep')

if __name__=='__main__':unittest.main()
