import {UNKNOWN} from './filters';

// Build from the complete catalogue so filtering never changes a status colour.
export function buildStatusColours(statuses:Iterable<string>):Record<string,string>{
  const recorded=[...new Set([...statuses].map(status=>status||UNKNOWN))].sort();
  const familiar:Record<string,string>={Live:'#16864b',Complete:'#2563c7',[UNKNOWN]:'#9a9083'};
  let next=0;
  return Object.fromEntries(recorded.map(status=>[status,(Object.hasOwn(familiar,status)?familiar[status]:undefined)||`hsl(${(32+next++*137.508)%360}, 65%, 43%)`]));
}

import type {ProjectNode} from './types';
const palette=['#087f99','#8b45b5','#d57616','#2563c7','#518322','#c33f69','#078d7d','#a16b16'];
export function projectColour(node:ProjectNode,by:string,group:number,statusColours:Record<string,string>={},groupColours:Record<number,string>={}){
  if(by==='owner'){let hash=0;for(const c of node.owner)hash=(hash*31+c.charCodeAt(0))>>>0;return palette[hash%palette.length]}
  if(by==='status')return statusColours[node.status||'Not recorded']||'#9a9083';
  if(by==='group')return groupColours[group]||palette[group%palette.length];
  const value=(node[by as 'funding'|'technology']||[])[0]||'Not recorded';
  let hash=0;for(const c of value)hash=(hash*31+c.charCodeAt(0))>>>0;
  return palette[hash%palette.length];
}

