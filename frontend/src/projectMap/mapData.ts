import type {Drawing,GraphData,Lens,Match,Pair} from './types';
export type ProjectEvidence={revision:string;id:string;fields:Record<string,string>;passages:Record<string,{field:string;source_id:string;text:string}>};
export interface MapSource {
  graph(signal?:AbortSignal):Promise<GraphData>;
  drawing(data:GraphData,lens:Lens,key:string,signal?:AbortSignal):Promise<Drawing>;
  neighbours(data:GraphData,id:string,lens:Lens,signal?:AbortSignal):Promise<{revision:string;matches:Match[]}>;
  pair(data:GraphData,a:string,b:string,signal?:AbortSignal):Promise<Pair>;
  project(data:GraphData,id:string,signal?:AbortSignal):Promise<ProjectEvidence>;
}
const lensNames:Lens[]=['balanced','profile','source'];
export function decodeRow(buffer:ArrayBuffer,count:number){
  if(buffer.byteLength!==count*36)throw Error('Incomplete snapshot comparison file. Reload the map.');
  return {scores:new DataView(buffer,0,count*12),evidence:new DataView(buffer,count*12,count*24)};
}
export function rowScores(row:ReturnType<typeof decodeRow>,index:number):Omit<Match,'id'>{
  return Object.fromEntries(lensNames.map((key,k)=>{const v=row.scores.getFloat32(index*12+k*4,true);return [key,Number.isFinite(v)?v:null]})) as Omit<Match,'id'>;
}
export class StaticMapSource implements MapSource {
  private cache=new Map<string,unknown>();
  constructor(private base:URL){}
  private async request<T>(path:string,signal?:AbortSignal,binary=false):Promise<T>{
    const key=path;
    if(this.cache.has(key)){const value=this.cache.get(key);this.cache.delete(key);this.cache.set(key,value);return value as T}
    const response=await fetch(new URL(path,this.base),{signal});
    if(!response.ok)throw Error(`Snapshot file unavailable (${response.status}). Reload or extract the complete download.`);
    const value=binary?await response.arrayBuffer():await response.json();
    if(path!=='manifest.json'){
      this.cache.set(key,value);while(this.cache.size>24)this.cache.delete(this.cache.keys().next().value!);
    }
    return value as T;
  }
  graph(signal?:AbortSignal){return this.request<GraphData>('manifest.json',signal)}
  private root(data:GraphData){if(data.snapshot?.format!==1)throw Error('Unsupported map snapshot. Rebuild the standalone map.');return data.snapshot.root}
  private index(data:GraphData,id:string){const i=data.nodes.findIndex(n=>n.id===id);if(i<0)throw Error('Project is outside this snapshot.');return i}
  async drawing(data:GraphData,lens:Lens,key:string,signal?:AbortSignal){
    if(key==='6')return data.lenses[lens];
    return this.request<Drawing>(`${this.root(data)}layouts/${lens}/${key}.json`,signal);
  }
  private async row(data:GraphData,id:string,signal?:AbortSignal){return decodeRow(await this.request<ArrayBuffer>(`${this.root(data)}rows/${this.index(data,id)}.bin`,signal,true),data.nodes.length)}
  async neighbours(data:GraphData,id:string,_lens:Lens,signal?:AbortSignal){
    const row=await this.row(data,id,signal);
    return {revision:data.revision,matches:data.nodes.flatMap((n,j)=>n.id===id?[]:[{id:n.id,...rowScores(row,j)}])};
  }
  project(data:GraphData,id:string,signal?:AbortSignal){return this.request<ProjectEvidence>(`${this.root(data)}projects/${this.index(data,id)}.json`,signal)}
  async pair(data:GraphData,a:string,b:string,signal?:AbortSignal):Promise<Pair>{
    if(a===b)throw Error('Choose two different projects.');
    const j=this.index(data,b),i=this.index(data,a);
    const [row,left,right]=await Promise.all([this.row(data,a,signal),this.project(data,a,signal),this.project(data,b,signal)]);
    if(left.revision!==data.revision||right.revision!==data.revision)throw Error('Snapshot changed. Reload the map.');
    const evidence:Pair['evidence']=[];
    for(let k=0;k<3;k++){
      const aa=row.evidence.getInt32(j*24+k*8,true),bb=row.evidence.getInt32(j*24+k*8+4,true);
      if(aa<0||bb<0)continue;
      const pa=left.passages[String(aa)],pb=right.passages[String(bb)];
      if(!pa||!pb)throw Error('Snapshot evidence is incomplete. Rebuild the map.');
      evidence.push({a:pa,b:pb});
    }
    const shared:Pair['shared']={},different:Pair['different']={};
    for(const field of ['technology','themes','research','funding'] as const){
      const aa=new Set(data.nodes[i][field]),bb=new Set(data.nodes[j][field]);
      shared[field]=[...aa].filter(x=>bb.has(x)).sort();different[field]={a:[...aa].filter(x=>!bb.has(x)).sort(),b:[...bb].filter(x=>!aa.has(x)).sort()};
    }
    return {revision:data.revision,a,b,scores:rowScores(row,j),evidence,shared,different};
  }
}
