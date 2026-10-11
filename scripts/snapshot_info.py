"""Describe the actual packaged source dates, independently of the build date."""
import argparse
from collections import Counter
import json
from pathlib import Path
import zipfile


def describe(projects, built_at):
    def dates(key):
        values = sorted(str(p[key]) for p in projects if p.get(key))
        return {'recorded': len(values), 'missing': len(projects)-len(values),
                'earliest': values[0] if values else None, 'latest': values[-1] if values else None}
    return {'built_at': built_at, 'entries': len(projects),
            'owners': dict(sorted(Counter(p['owner'] for p in projects).items())),
            'dates': {key: dates(key) for key in (
                'source_checked_at', 'detail_last_checked_at', 'financial_checked_at', 'imported_at')},
            'note': 'Build time is not a fresh ENA check. Imported records may have no independently checked source date.'}


def summary(info):
    lines = [f"Snapshot: **{info['entries']} projects**. Package built **{info['built_at']}**.", '',
             '| Source timestamp | Earliest → latest (UTC) | Records with date |',
             '| --- | --- | --- |']
    for key, label in [('source_checked_at', 'Project source checked'),
                       ('detail_last_checked_at', 'Project detail checked'),
                       ('financial_checked_at', 'Financial fields checked'), ('imported_at', 'File imported')]:
        date = info['dates'][key]
        span = f"{date['earliest']} → {date['latest']}" if date['recorded'] else 'Not recorded'
        lines.append(f"| {label} | {span} | {date['recorded']}/{info['entries']} |")
    lines += ['', info['note'], '', 'Included owners: '+', '.join(f"{owner} ({count})" for owner,count in info['owners'].items())+'.']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, default=Path('outputs/energy-network-map.zip'))
    parser.add_argument('--write-readme', type=Path)
    args = parser.parse_args()
    with zipfile.ZipFile(args.archive) as archive:
        info = json.loads(archive.read('energy-network-map/snapshot-info.json'))
    block = summary(info)
    if args.write_readme:
        start, end = '<!-- snapshot-start -->', '<!-- snapshot-end -->'
        text = args.write_readme.read_text()
        before, separator, rest = text.partition(start)
        _, closing, after = rest.partition(end)
        if not separator or not closing:
            raise ValueError('README snapshot markers are missing')
        args.write_readme.write_text(before+start+'\n'+block+'\n'+end+after)
    print(block)


if __name__ == '__main__':
    main()
