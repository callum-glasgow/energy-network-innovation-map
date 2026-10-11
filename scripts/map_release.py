"""Portable static-map validation, checksums and safe Release extraction. Standard library only."""
import argparse
import hashlib
import json
import math
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_SITE_BYTES = 950_000_000
ALLOWED = {'.html', '.css', '.js', '.json', '.bin', '.py', '.command', '.bat', '.txt'}

def source_fingerprint(root):
    """Hash build/import source, never local data, caches, credentials or Git metadata."""
    root=Path(root)
    suffixes={'.py','.sh','.txt','.json','.ts','.tsx','.css','.html','.yml','.command','.bat'}
    paths=[]
    for name in ('frontend/src','frontend/map','map-package','core','adapters','scripts'):
        paths.extend(p for p in (root/name).rglob('*') if p.is_file() and p.suffix in suffixes)
    paths.extend(root/name for name in ('frontend/package.json','frontend/bun.lock','frontend/tsconfig.json',
        'frontend/vite.map.config.ts','requirements.txt','.github/workflows/deploy-map.yml'))
    digest=hashlib.sha256()
    for path in sorted(set(paths)):
        digest.update(path.relative_to(root).as_posix().encode()+b'\0'+sha256(path).encode()+b'\n')
    return digest.hexdigest()

def sha256(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda:source.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_checksums(site):
    site=Path(site)
    records={p.relative_to(site).as_posix():sha256(p) for p in sorted(site.rglob('*')) if p.is_file() and p.name!='checksums.json'}
    (site/'checksums.json').write_text(json.dumps(records,sort_keys=True)+'\n')


def validate_site(site):
    site=Path(site)
    files=[p for p in site.rglob('*') if p.is_file()]
    if any(p.is_symlink() for p in site.rglob('*')):
        raise ValueError('Static map must not contain symbolic links')
    size=sum(p.stat().st_size for p in files)
    if size>=MAX_SITE_BYTES:
        raise ValueError('Static map approaches the GitHub Pages 1 GB limit')
    for p in files:
        if p.name!='.nojekyll' and p.suffix.lower() not in ALLOWED:
            raise ValueError(f'Unexpected file in public map: {p.relative_to(site)}')
    checksums=json.loads((site/'checksums.json').read_text())
    names={p.relative_to(site).as_posix() for p in files if p.name!='checksums.json'}
    if set(checksums)!=names or any(sha256(site/name)!=checksums[name] for name in names):
        raise ValueError('Public map checksum mismatch')
    html=(site/'index.html').read_text()
    for relative in re.findall(r'(?:src|href)="(\./assets/[^"]+)"',html):
        if not (site/relative).is_file():
            raise ValueError(f'Missing frontend asset: {relative}')
    manifest=json.loads((site/'data/manifest.json').read_text())
    build=json.loads((site/'build-info.json').read_text())
    if build.get('revision')!=manifest['revision'] or not re.fullmatch(r'[a-f0-9]{64}',build.get('source_fingerprint','')):
        raise ValueError('Invalid build provenance')
    nodes=manifest['nodes'];count=len(nodes)
    if not count or len({n['id'] for n in nodes})!=count:
        raise ValueError('Empty or duplicate project identities')
    root=manifest['snapshot']['root']
    if root!=manifest['revision']+'/' or not re.fullmatch(r'[a-f0-9]{64}/',root):
        raise ValueError('Invalid public snapshot root')
    data=site/'data'/root
    expected_paths=set()
    for i,node in enumerate(nodes):
        detail=json.loads((data/'projects'/f'{i}.json').read_text())
        if detail['id']!=node['id'] or detail['revision']!=manifest['revision']:
            raise ValueError('Project detail does not match the manifest')
        if (data/'rows'/f'{i}.bin').stat().st_size!=count*36:
            raise ValueError('Comparison row is missing or truncated')
        expected_paths.update({f'projects/{i}.json',f'rows/{i}.bin'})
    for lens,drawing in manifest['lenses'].items():
        variants=[drawing]
        for key in ('4','5','7','8','9','10','first','second'):
            name=f'layouts/{lens}/{key}.json';expected_paths.add(name)
            variants.append(json.loads((data/name).read_text()))
        if len(manifest['connection_proximity'][lens])!=count:
            raise ValueError('Connection explanations do not cover the catalogue')
        for variant in variants:
            if len(variant['positions'])!=count or len(variant['groups'])!=count:
                raise ValueError('Drawing does not cover the catalogue')
            if any(len(p)!=2 or not all(math.isfinite(v) for v in p) for p in variant['positions']):
                raise ValueError('Invalid map positions')
            if any(not 0<=a<count or not 0<=b<count or not math.isfinite(score) for a,b,score in variant['edges']):
                raise ValueError('Invalid map edge')
    actual={p.relative_to(data).as_posix() for p in data.rglob('*') if p.is_file()}
    if actual!=expected_paths:
        raise ValueError('Unexpected or missing public snapshot files')
    if {p.name for p in (site/'data').iterdir()}!={manifest['revision'],'manifest.json','review-pack.json'}:
        raise ValueError('Static package must contain exactly one current revision')
    for name in ('serve.py','Start map.command','Start map.bat','README.txt','.nojekyll'):
        if not (site/name).is_file():
            raise ValueError(f'Missing local-download file: {name}')
    return {'revision':manifest['revision'],'entries':count,'site_bytes':size,'checksums_verified':len(names),
            'source_fingerprint':build['source_fingerprint']}


def extract_release(archive,destination,source_root=None):
    destination=Path(destination)
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('Extraction destination must be empty')
    with zipfile.ZipFile(archive) as package:
        entries=package.infolist();seen=set()
        if sum(p.file_size for p in entries)>=MAX_SITE_BYTES:
            raise ValueError('Release exceeds the supported Pages size')
        for entry in entries:
            path=PurePosixPath(entry.filename)
            mode=entry.external_attr>>16
            if ('\\' in entry.filename or path.is_absolute() or '..' in path.parts or
                len(path.parts)<2 or path.parts[0]!='energy-network-map' or
                stat.S_ISLNK(mode) or path.as_posix() in seen):
                raise ValueError('Unsafe or duplicate Release path')
            seen.add(path.as_posix())
            if not entry.is_dir() and stat.S_IFMT(mode) not in (0,stat.S_IFREG):
                raise ValueError('Release contains a non-regular file')
        destination.parent.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
            temp=Path(temp)
            for entry in entries:
                relative=PurePosixPath(entry.filename).relative_to('energy-network-map')
                target=temp/relative
                if entry.is_dir():
                    target.mkdir(parents=True,exist_ok=True)
                else:
                    target.parent.mkdir(parents=True,exist_ok=True)
                    with package.open(entry) as source,target.open('wb') as output:
                        shutil.copyfileobj(source,output)
            result=validate_site(temp)
            if source_root is not None and result['source_fingerprint']!=source_fingerprint(source_root):
                raise ValueError('Package source differs from this checkout. Rebuild the map before publishing.')
            if destination.exists():destination.rmdir()
            shutil.copytree(temp,destination)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path);parser.add_argument('destination',type=Path)
    parser.add_argument('--source-root',type=Path)
    args=parser.parse_args()
    print(json.dumps(extract_release(args.archive,args.destination,args.source_root),indent=2))
if __name__=='__main__':main()
