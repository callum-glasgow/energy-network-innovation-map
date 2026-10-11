"""Build and validate a standalone map and local ZIP; never publishes to GitHub."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from core.config import ROOT
from core.map_export import export_map
from core.storage import Store, now
from scripts.map_release import sha256, validate_site, write_checksums, source_fingerprint
from scripts.snapshot_info import describe, summary


def replace_directory(source,target):
    source,target=Path(source),Path(target)
    target.parent.mkdir(parents=True,exist_ok=True)
    previous=target.with_name(target.name+'.previous-'+uuid.uuid4().hex)
    if target.exists():os.replace(target,previous)
    try:
        os.replace(source,target)
    except BaseException:
        if previous.exists():os.replace(previous,target)
        raise
    if previous.exists():shutil.rmtree(previous)


def build(destination=None,database=None,archive=None,report=None,compatibility=True):
    target=Path(destination).resolve() if destination else ROOT/'frontend/map-dist'
    archive=Path(archive).resolve() if archive else ROOT/'outputs/energy-network-map.zip'
    target.parent.mkdir(parents=True,exist_ok=True);archive.parent.mkdir(parents=True,exist_ok=True)
    source_version=source_fingerprint(ROOT)
    with tempfile.TemporaryDirectory(prefix='.map-build-',dir=target.parent) as temporary:
        site=Path(temporary)/'site'
        subprocess.run(['bun','run','build:map','--outDir',str(site)],cwd=ROOT/'frontend',check=True)
        store=Store(database) if database else Store()
        stats=export_map(store,site/'data')
        snapshot=describe(store.projects(),now())
        (site/'.nojekyll').write_text('')
        for name in ('serve.py','Start map.command','Start map.bat','README.txt'):
            shutil.copy2(ROOT/'map-package'/name,site/name)
        (site/'snapshot-info.json').write_text(json.dumps(snapshot,indent=2)+'\n')
        with (site/'README.txt').open('a') as readme:
            readme.write('\nACTUAL DATA DATES\n\n'+summary(snapshot)+'\n')
        if source_fingerprint(ROOT)!=source_version:
            raise ValueError('Source changed while building. Repeat the build from the current source.')
        (site/'build-info.json').write_text(json.dumps({'revision':stats['revision'],
            'built_at':now(),'source_fingerprint':source_version},sort_keys=True)+'\n')
        write_checksums(site)
        stats.update(validate_site(site))
        pending=archive.with_name(archive.name+'.tmp')
        try:
            with zipfile.ZipFile(pending,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
                for path in sorted(site.rglob('*')):
                    if path.is_file():output.write(path,Path('energy-network-map')/path.relative_to(site))
            with zipfile.ZipFile(pending) as output:
                if output.testzip() is not None:raise ValueError('ZIP verification failed')
            # The previous site remains usable throughout compilation and validation.
            replace_directory(site,target)
            os.replace(pending,archive)
        finally:
            pending.unlink(missing_ok=True)
    legacy=ROOT/'frontend/dist/map'
    if compatibility and (ROOT/'frontend/dist/index.html').exists():
        with tempfile.TemporaryDirectory(prefix='.map-copy-',dir=legacy.parent) as temporary:
            copied=Path(temporary)/'site';shutil.copytree(target,copied);replace_directory(copied,legacy)
    stats.update({'site':str(target),'archive':str(archive),'zip_bytes':archive.stat().st_size,
                  'archive_sha256':sha256(archive)})
    report=Path(report) if report else ROOT/'docs'/f'map-build-{now()[:10]}.json'
    report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(stats,indent=2)+'\n')
    print(json.dumps(stats,indent=2));return stats

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination',type=Path);parser.add_argument('--database',type=Path)
    args=parser.parse_args();build(args.destination,args.database)
