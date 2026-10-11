"""Maintain optional passage search after source changes; never regenerate Luna.

Run without --live to inspect coverage. --live embeds only missing exact texts
using the existing model/dimensions and budget. Search never builds this index.
"""
import argparse
import json
from core.storage import Store
from core.passage_search import chunks, key


def missing_passages(store):
    index=store.keyword_snapshot();active=chunks(index.projects,index.passages)
    from core.config import EMBEDDING,DIMENSIONS
    with store.connect() as c:
        present={r[0] for r in c.execute('SELECT cache_key FROM passage_vectors WHERE model=? AND dimensions=?',(EMBEDDING,DIMENSIONS))}
    return active,[p for p in active if key(p['text']) not in present]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');args=parser.parse_args()
    store=Store();active,pending=missing_passages(store)
    print(json.dumps({'active_passages':len(active),'missing':len(pending),'paid_generation':args.live},indent=2))
    if not args.live:return
    from adapters.models.openai import OpenAI
    model=OpenAI()
    for i,chunk in enumerate(pending,1):
        vector=model.embedding(chunk['text'],'original passage embedding')
        store.save_passage_vectors([(chunk['text'],vector)])
        print(f'{i}/{len(pending)} embedded',flush=True)


if __name__=='__main__':main()
