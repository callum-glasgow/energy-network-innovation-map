"""Download a complete, GUID-preserving ENA source file. Makes no model calls."""
import argparse
import json
from pathlib import Path
from adapters.ena.downloads import download

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=['spen','all'], default='spen')
    parser.add_argument('--output', type=Path, default=Path('data/inbox/ena-projects.json'))
    args=parser.parse_args()
    result=download(args.scope,lambda done,total:print(f'Downloaded {done}/{total}',flush=True))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary=args.output.with_suffix(args.output.suffix+'.tmp')
    temporary.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    temporary.replace(args.output)
    print(f'Saved {len(result["projects"])} projects to {args.output}. No API charges.')
if __name__=='__main__':main()
