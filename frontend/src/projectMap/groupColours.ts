import type {Drawing} from './types';

// Oklab conversion from Björn Ottosson's public-domain reference implementation:
// https://bottosson.github.io/posts/oklab/
function lab(hex:string){
  const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  const[r,g,b]=rgb,l=Math.cbrt(.4122214708*r+.5363325363*g+.0514459929*b),m=Math.cbrt(.2119034982*r+.6806995451*g+.1073969566*b),s=Math.cbrt(.0883024619*r+.2817188376*g+.6299787005*b);
  return [.2104542553*l+.793617785*m-.0040720468*s,1.9779984951*l-2.428592205*m+.4505937099*s,.0259040371*l+.7827717662*m-.808675766*s];
}
export function colourDistance(a:string,b:string){const x=lab(a),y=lab(b);return Math.hypot(...x.map((v,i)=>v-y[i]))}
const palette=['#2563eb','#ea580c','#008777','#c026d3','#65a30d','#6d28d9','#ca8a04','#dc2626','#0891b2','#db2777','#854d0e','#14532d','#332066','#fb923c','#78b727','#dd4fc8'];
const distances=palette.map(a=>palette.map(b=>colourDistance(a,b)));

// Connect groups that share a retained edge or lie next to each other on screen.
// Work from the whole drawing, so filtering cannot change the colour assignments.
export function groupNeighbours(layout:Drawing,extraEdges:number[][]=[]){
  const centers=new Map<number,{x:number;y:number;n:number}>();
  layout.groups.forEach((g,i)=>{const c=centers.get(g)||{x:0,y:0,n:0};c.x+=layout.positions[i][0];c.y+=layout.positions[i][1];c.n++;centers.set(g,c)});
  for(const c of centers.values()){c.x/=c.n;c.y/=c.n}
  const ids=[...centers.keys()].sort((a,b)=>a-b),adj=new Map(ids.map(g=>[g,new Set<number>()]));
  function connect(a:number,b:number){if(a!==b){adj.get(a)!.add(b);adj.get(b)!.add(a)}}
  for(const[a,b]of [...layout.edges,...extraEdges])connect(layout.groups[a],layout.groups[b]);
  const nearestDistances:number[]=[];
  for(const g of ids){const p=centers.get(g)!;const near=ids.filter(h=>h!==g).sort((a,b)=>{const x=centers.get(a)!,y=centers.get(b)!;return (p.x-x.x)**2+(p.y-x.y)**2-((p.x-y.x)**2+(p.y-y.y)**2)||a-b});for(const h of near.slice(0,4))connect(g,h);if(near.length){const q=centers.get(near[0])!;nearestDistances.push(Math.hypot(p.x-q.x,p.y-q.y))}}
  // Unlinked singleton groups should not crowd out the labelled clusters' neighbours.
  const named=layout.communities.map(c=>c.id).filter(g=>centers.has(g));
  for(const g of named){const p=centers.get(g)!;const near=named.filter(h=>h!==g).sort((a,b)=>{const x=centers.get(a)!,y=centers.get(b)!;return (p.x-x.x)**2+(p.y-x.y)**2-((p.x-y.x)**2+(p.y-y.y)**2)||a-b});for(const h of near.slice(0,6))connect(g,h)}
  // Also protect group boundaries: nearby member nodes can have distant centroids.
  nearestDistances.sort((a,b)=>a-b);
  const radius=Math.max(1,(nearestDistances[Math.floor(nearestDistances.length/2)]||2)/2),grid=new Map<string,number[]>();
  layout.positions.forEach(([x,y],i)=>{
    const cx=Math.floor(x/radius),cy=Math.floor(y/radius);
    for(let dx=-1;dx<=1;dx++)for(let dy=-1;dy<=1;dy++)for(const j of grid.get(`${cx+dx},${cy+dy}`)||[]){const [a,b]=layout.positions[j];if((x-a)**2+(y-b)**2<=radius*radius)connect(layout.groups[i],layout.groups[j])}
    const key=`${cx},${cy}`,bucket=grid.get(key)||[];bucket.push(i);grid.set(key,bucket);
  });
  return adj;
}
export function buildGroupColours(layout:Drawing,extraEdges:number[][]=[]):Record<number,string>{
  const adj=groupNeighbours(layout,extraEdges),assigned=new Map<number,number>(),remaining=new Set(adj.keys());
  const used=Array(palette.length).fill(0);
  while(remaining.size){
    const ordered=[...remaining].sort((a,b)=>new Set([...adj.get(b)!].map(g=>assigned.get(g)).filter(c=>c!==undefined)).size-new Set([...adj.get(a)!].map(g=>assigned.get(g)).filter(c=>c!==undefined)).size||adj.get(b)!.size-adj.get(a)!.size||a-b);
    const g=ordered[0],neighbours=[...adj.get(g)!].filter(h=>assigned.has(h));
    let best=0,score=-Infinity;
    for(let c=0;c<palette.length;c++){
      const contrast=neighbours.length?Math.min(...neighbours.map(h=>distances[c][assigned.get(h)!])):1;
      const value=contrast-used[c]*.0001;
      if(value>score){score=value;best=c}
    }
    assigned.set(g,best);used[best]++;remaining.delete(g);
  }
  // Improve the worst local contrast after the greedy pass, with deterministic ties.
  for(let pass=0;pass<4;pass++)for(const g of adj.keys()){
    const near=[...adj.get(g)!];if(!near.length)continue;
    let best=assigned.get(g)!,score=Math.min(...near.map(h=>distances[best][assigned.get(h)!]));
    for(let c=0;c<palette.length;c++){const value=Math.min(...near.map(h=>distances[c][assigned.get(h)!]));if(value>score+1e-6){best=c;score=value}}
    assigned.set(g,best);
  }
  return Object.fromEntries([...assigned].map(([g,c])=>[g,palette[c]]));
}
