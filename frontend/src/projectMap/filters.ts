import type {ProjectNode} from './types';
export const UNKNOWN='Not recorded';
export function projectIdMatches(nodes:ProjectNode[],query:string){
  const exact=query.trim().toLowerCase();
  if(!exact)return [];
  const guid=nodes.find(n=>n.id.toLowerCase()===exact);
  if(guid)return [guid];
  const reference=exact.replace(/\s/g,'');
  return nodes.filter(n=>n.reference.replace(/\s/g,'').toLowerCase()===reference);
}
export const facets=['owner','status','sector','participants','funding','technology','themes','research'] as const;
export type Facet=typeof facets[number];
export type Filters={query:string; facets:Record<Facet,string[]>;live:string;dateMode:string;from:string;to:string;asof:string;unknownEnd:boolean;preceding:string;includeTest:boolean};
export function londonToday(now=new Date()){return new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/London',year:'numeric',month:'2-digit',day:'2-digit'}).format(now)}
export function emptyFilters():Filters{return {query:'',facets:{owner:[],status:[],sector:[],participants:[],funding:[],technology:[],themes:[],research:[]},live:'',dateMode:'',from:'',to:'',asof:londonToday(),unknownEnd:false,preceding:'',includeTest:true}}
export function facetValues(p:ProjectNode,key:Facet):string[]{const value=p[key];return (Array.isArray(value)?value.length?value:[UNKNOWN]:[value||UNKNOWN])}
export function matches(p:ProjectNode,f:Filters,skip?:Facet){
  const q=f.query.trim().toLowerCase();
  if(q && ![p.title,p.reference,p.id].some(v=>v.toLowerCase().includes(q)))return false;
  if(!f.includeTest&&p.flags.includes('Apparent test record'))return false;
  for(const key of facets)if(key!==skip&&f.facets[key].length&&!f.facets[key].some(v=>facetValues(p,key).includes(v)))return false;
  if(f.live==='yes'&&p.status!=='Live')return false;
  if(f.live==='no'&&(p.status==='Live'||p.status===UNKNOWN||p.status==='Unknown'))return false;
  if(f.preceding==='yes'&&!p.preceding.length)return false;
  if(f.preceding==='no'&&p.preceding.length)return false;
  if(f.preceding==='unresolved'&&!p.preceding.some(x=>x.state!=='resolved'))return false;
  if(f.dateMode){
    if(p.invalid_dates)return false;
    if(f.dateMode==='active'){
      if(!f.asof||!p.start_date||p.start_date>f.asof)return false;
      if(!p.end_date&&!f.unknownEnd)return false;
      if(p.end_date&&p.end_date<f.asof)return false;
    }else if(f.dateMode==='overlap'){
      if(f.from&&f.to&&f.from>f.to)return false;
      if(f.to&&(!p.start_date||p.start_date>f.to))return false;
      if(f.from&&(!p.end_date?!f.unknownEnd:p.end_date<f.from))return false;
    }else{
      const value=f.dateMode==='start'?p.start_date:p.end_date;
      if((f.from||f.to)&&(!value||f.from&&value<f.from||f.to&&value>f.to))return false;
    }
  }
  return true;
}
export function facetCounts(nodes:ProjectNode[],f:Filters,key:Facet){
  const counts=new Map<string,number>();
  for(const p of nodes.filter(p=>matches(p,f,key)))for(const v of facetValues(p,key))counts.set(v,(counts.get(v)||0)+1);
  // Keep selected zero-result values visible and removable.
  for(const v of f.facets[key])if(!counts.has(v))counts.set(v,0);
  return [...counts].sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0]));
}
export function moneyLabel(value:number|null){return value===null?'Not recorded':new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',maximumFractionDigits:0}).format(value)}
export function compactMoney(value:number){return new Intl.NumberFormat('en-GB',{style:'currency',currency:'GBP',notation:'compact',maximumFractionDigits:1}).format(value)}
export function sizeFor(value:number|null,max:number,compressed:boolean){
  if(value===null)return 12;
  if(value===0)return 3;
  return compressed?8+64*Math.log1p(value)/Math.log1p(max||1):72*Math.sqrt(value/(max||1));
}

export function dateLabel(value:string|null){return value?new Date(value+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}):'Not recorded'}
