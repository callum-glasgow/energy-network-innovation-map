"""Preview a verified GitHub Release; --publish explicitly uploads it. Never commits or pushes source."""
import argparse
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path
from core.config import ROOT
from scripts.map_release import extract_release, sha256
from scripts.snapshot_info import summary


def command(arguments, **kwargs):
    return subprocess.run(arguments, check=True, text=True, capture_output=True, **kwargs).stdout.strip()


def publish(archive=None, *, repo, tag=None, execute=False):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Use --repo OWNER/REPOSITORY')
    archive = Path(archive or ROOT/'outputs/energy-network-map.zip').resolve()
    with tempfile.TemporaryDirectory(prefix='map-release-check-') as temporary:
        result = extract_release(archive, Path(temporary)/'site', source_root=ROOT)
    fingerprint = sha256(archive)
    tag = tag or 'map-'+fingerprint[:16]
    if not re.fullmatch(r'map-[A-Za-z0-9][A-Za-z0-9._-]{0,100}', tag) or '..' in tag:
        raise ValueError('Release tag must start map- and contain only letters, digits, dots, underscores or hyphens')
    result.update(repo=repo, tag=tag, archive=str(archive), archive_sha256=fingerprint, published=False)
    if not execute:
        print(json.dumps(result, indent=2)); return result
    if archive.name != 'energy-network-map.zip':
        raise ValueError('Release archive must be named energy-network-map.zip for the Pages workflow')
    if not (ROOT/'.github/workflows/deploy-map.yml').is_file():
        raise ValueError('Missing Pages workflow')
    if command(['git','status','--porcelain'], cwd=ROOT):
        raise ValueError('Commit the source changes first, then push them to the intended repository. Generated data stays ignored.')
    commit = command(['git','rev-parse','HEAD'], cwd=ROOT)
    # This verifies that --target refers to this source version in the explicitly chosen repository.
    command(['gh','api',f'repos/{repo}/commits/{commit}','--silent'], cwd=ROOT)
    refs = json.loads(command(['gh','api',f'repos/{repo}/git/matching-refs/tags/{tag}'], cwd=ROOT))
    if any(ref.get('ref') == 'refs/tags/'+tag for ref in refs):
        raise ValueError('Release tag already exists. Choose a new --tag; existing tags are never reused or overwritten.')
    notes = (f'Energy network innovation map: {result["entries"]} projects.\n\n'
             f'Download energy-network-map.zip, extract it and follow README.txt to run locally with Python 3. '
             f'The same package is deployed to GitHub Pages by the release workflow.\n\n'
             f'Snapshot revision: {result["revision"]}\nSource commit: {commit}\n'
             f'Archive SHA-256: {fingerprint}\n')
    with zipfile.ZipFile(archive) as package:
        if 'energy-network-map/snapshot-info.json' in package.namelist():
            notes += '\n'+summary(json.loads(package.read('energy-network-map/snapshot-info.json')))+'\n'
    with tempfile.TemporaryDirectory(prefix='map-release-notes-') as temporary:
        path = Path(temporary)/'notes.md'; path.write_text(notes)
        output = command(['gh','release','create',tag,str(archive),'--repo',repo,'--target',commit,
                          '--title',f'Project map · {result["entries"]} entries', '--notes-file',str(path)], cwd=ROOT)
    result.update(published=True, release=output)
    print(json.dumps(result, indent=2)); return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path); parser.add_argument('--repo', required=True)
    parser.add_argument('--tag'); parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    try:
        publish(args.archive, repo=args.repo, tag=args.tag, execute=args.publish)
    except subprocess.CalledProcessError as error:
        parser.exit(1, f'Git/GitHub command failed (exit {error.returncode}). Check git, gh auth status, the pushed commit and repository permissions. No automatic retry.\n')
    except (ValueError, OSError) as error:
        parser.exit(1, f'{error}\n')
if __name__ == '__main__':main()
