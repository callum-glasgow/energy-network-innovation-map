import type {Drawing,GraphData,Lens,Match,ProjectNode} from './types';

export function connectionExplanation(data:GraphData,layout:Drawing,node:ProjectNode,lens:Lens,visible:Set<string>,matches?:Match[]){
  const index=data.nodes.findIndex(n=>n.id===node.id);
  const links=layout.edges.filter(([a,b])=>a===index||b===index);
  if(links.some(([a,b])=>visible.has(data.nodes[a].id)&&visible.has(data.nodes[b].id)))return null;
  if(links.length)return 'Its linked projects are outside the current filters.';
  if((lens!=='source'&&!node.coverage.profile)||(lens!=='profile'&&!node.coverage.complete))return 'Similarity data is incomplete for this project, so some links cannot be calculated.';
  if(!matches)return 'No link at this setting: matches must pass the similarity cutoff and be selected by both projects.';
  const available=matches.filter(m=>m[lens]!==null);
  if(!available.length)return 'No compatible similarity scores are available for this project.';
  const rawFloor=Number(data.method.raw_floor??.35),floor=lens==='balanced'?Number(data.method.balanced_floor??.85):rawFloor;
  const qualifies=available.some(m=>m[lens]!>=floor&&(lens!=='balanced'||Math.max(m.profile??-Infinity,m.source??-Infinity)>=rawFloor));
  return qualifies?'No mutual match at this setting: a link must be selected by both projects.':'Its matches are below the similarity cutoff at this setting.';
}

export function hoverGroup(layout:Drawing,index:number){
  const id=layout.groups[index],community=layout.communities.find(c=>c.id===id);
  return {id,label:`Group ${id+1} · ${community?.label||(layout.isolated.includes(index)?'Unlinked project':'Small similarity group')}`};
}

export function connectionDistance(data:GraphData,layout:Drawing,node:ProjectNode,lens:Lens,linkKey:string,matches?:Match[]){
  const index=data.nodes.findIndex(n=>n.id===node.id);
  if(!layout.isolated.includes(index))return null;
  const proximity=data.connection_proximity?.[lens]?.[index];
  if(proximity?.minimum_neighbours!=null){
    const required=proximity.minimum_neighbours,current=Number(linkKey),max=Number(data.method.fixed_max??10);
    const delta=Number.isInteger(current)&&current>0&&required>current?` (${required-current} more than the current ${current})`:'';
    return `First link across saved projects: ${required} neighbours${delta}. Ranks for that pair: ${proximity.rank} and ${proximity.reverse_rank}.${required>max?` Above the current setting limit of ${max}.`:''}`;
  }
  if(!matches)return null;
  const available=matches.filter(m=>m[lens]!==null).sort((a,b)=>b[lens]!-a[lens]!);
  if(!available.length)return null;
  const best=available[0],rawFloor=Number(data.method.raw_floor??.35),floor=lens==='balanced'?Number(data.method.balanced_floor??.85):rawFloor;
  const score=best[lens]!;
  // Missing proximity in an older snapshot must not imply that no link is possible.
  const qualified=available.some(m=>m[lens]!>=floor&&(lens!=='balanced'||Math.max(m.profile??-Infinity,m.source??-Infinity)>=rawFloor));
  if(qualified)return null;
  if(score<floor){
    const digits=floor-score<.0001?6:4;
    return `Best ${lens==='balanced'?'balanced ':''}score: ${score.toFixed(digits)}; cutoff: ${floor.toFixed(digits)} (gap ${(floor-score).toFixed(digits)}). More neighbours alone cannot add a link.`;
  }
  const raw=Math.max(best.profile??-Infinity,best.source??-Infinity);
  if(Number.isFinite(raw)&&raw<rawFloor)return `Best match passes the balanced cutoff, but its raw score is ${raw.toFixed(4)}; it needs ${rawFloor.toFixed(4)} (gap ${(rawFloor-raw).toFixed(4)}). More neighbours alone cannot add a link.`;
  return null;
}
