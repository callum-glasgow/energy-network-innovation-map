import {expect,test} from 'bun:test';
import type {Drawing} from '../src/projectMap/types';
import {buildGroupColours,colourDistance,groupNeighbours} from '../src/projectMap/groupColours';
import {overviewZoom,statusShape,statusSizeFactor} from '../src/projectMap/viewport';
const layout={positions:Array.from({length:16},(_,i)=>[i%4*100,Math.floor(i/4)*100]),groups:Array.from({length:16},(_,i)=>i),edges:[[0,15,.9],[1,14,.8]],communities:Array.from({length:16},(_,id)=>({id,label:`Group ${id}`,count:5,x:id%4*100,y:Math.floor(id/4)*100})),isolated:[],components:1,cutoff_counts:[],fallbacks:[]} as Drawing;
test('connected and spatially neighbouring groups get contrasting colours, deterministically',()=>{
  const colours=buildGroupColours(layout),adj=groupNeighbours(layout);
  expect(adj.get(0)?.has(15)).toBe(true);expect(adj.get(0)?.has(1)).toBe(true);
  for(const[g,near]of adj)for(const h of near){expect(colours[g]).not.toBe(colours[h]);expect(colourDistance(colours[g],colours[h])).toBeGreaterThan(.14)}
  expect(groupNeighbours(layout,[[0,10]]).get(0)?.has(10)).toBe(true);
  expect(colourDistance(buildGroupColours(layout,[[0,10]])[0],buildGroupColours(layout,[[0,10]])[10])).toBeGreaterThan(.14);
  expect(buildGroupColours({...layout,edges:[...layout.edges].reverse()})).toEqual(colours);
});
test('overview zoom responds to visible bounds and viewport, with no arbitrary far-out floor',()=>{
  expect(overviewZoom(1000,600,{w:2000,h:1000})).toBeCloseTo(.44);expect(overviewZoom(600,1000,{w:2000,h:1000})).toBeCloseTo(.24);
  expect(overviewZoom(1000,600,{w:100000,h:10000})).toBeCloseTo(.0088);expect(overviewZoom(1000,600,{w:20,h:20})).toBe(1.4);expect(overviewZoom(50,50,{w:0,h:0})).toBeGreaterThan(0);
});
test('status shapes preserve proportional investment area and do not invent Live for unknowns',()=>{
  expect(statusShape('Live')).toBe('diamond');expect(statusShape('Complete')).toBe('ellipse');expect(statusShape('')).toBe('rectangle');
  const area=(status:string,d:number)=>d*d*statusSizeFactor(status)**2*(status==='Live'?.5:status==='Complete'?Math.PI/4:1);
  for(const status of ['Live','Complete','Not recorded']){expect(area(status,10)).toBeCloseTo(Math.PI*25);expect(area(status,20)/area(status,10)).toBeCloseTo(4)}
});
