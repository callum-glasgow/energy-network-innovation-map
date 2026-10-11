import type {GraphData,ProjectNode} from './types';

export function connectedProjects(nodes:ProjectNode[],edges:number[][],lineage:GraphData['lineage'],included:Set<string>,similarity:boolean,predecessors:boolean){
  const connected=new Set<string>();
  function add(a:string,b:string){if(a!==b&&included.has(a)&&included.has(b)){connected.add(a);connected.add(b)}}
  if(similarity)for(const[a,b]of edges)add(nodes[a].id,nodes[b].id);
  if(predecessors)for(const edge of lineage)add(edge.source,edge.target);
  return connected;
}
