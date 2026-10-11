"""A small blinded human-review pack; no generated relevance labels."""
import random
import numpy as np

def review_pack(engine,bundle):
    nodes=bundle['public']['nodes'];arrays=bundle['arrays'];seen=set();pairs=[]
    for mode in ('strong','weak','disagreement'):
        candidates=[]
        matrix=abs(arrays['profile_rank']-arrays['source_rank']) if mode=='disagreement' else arrays['balanced']
        for i,row in enumerate(matrix):
            valid=np.flatnonzero(np.isfinite(row))
            if not len(valid):continue
            j=int(valid[np.argmin(row[valid]) if mode=='weak' else np.argmax(row[valid])])
            a,b=sorted((i,j))
            candidates.append((float(row[j])*(-1 if mode=='weak' else 1),a,b))
        represented=set();count=0
        for _,i,j in sorted(candidates,reverse=True):
            if (i,j) in seen or mode=='strong' and (i in represented or j in represented):continue
            pair=engine.pair(nodes[i]['id'],nodes[j]['id'])
            pairs.append({'a':{k:nodes[i][k] for k in ('id','title','reference','owner')},
                          'b':{k:nodes[j][k] for k in ('id','title','reference','owner')},
                          'evidence':pair['evidence'],'grade':'','reason':''})
            seen.add((i,j));represented.update((i,j));count+=1
            if count==20:break
    random.Random(73).shuffle(pairs)
    return {'revision':bundle['public']['revision'],'instructions':'Independently review original evidence. Grade as directly reusable learning, related background, superficially similar, unrelated, or insufficient evidence; explain why. Scores and sampling categories are hidden. This is a pilot set, not a comprehensive or held-out benchmark.', 'pairs':pairs}
