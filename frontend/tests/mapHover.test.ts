import {expect,test} from 'bun:test';
import {connectionDistance} from '../src/projectMap/hoverDetails';
import type {Drawing,GraphData,ProjectNode} from '../src/projectMap/types';
const node={id:'a'} as ProjectNode;
const drawing={isolated:[0]} as Drawing;
const data={nodes:[node],method:{fixed_max:10,raw_floor:.35,balanced_floor:.85},connection_proximity:{balanced:[{minimum_neighbours:8,rank:3,reverse_rank:8}]}} as unknown as GraphData;
test('hover reports required mutual rank and distance from the selected fixed setting',()=>{
  expect(connectionDistance(data,drawing,node,'balanced','6')).toContain('8 neighbours (2 more than the current 6)');
  expect(connectionDistance(data,drawing,node,'balanced','first')).toContain('Ranks for that pair: 3 and 8');
  expect(connectionDistance(data,drawing,node,'balanced','first')).not.toContain('more than');
  expect(connectionDistance(data,{isolated:[]} as unknown as Drawing,node,'balanced','6')).toBeNull();
  const distant={...data,connection_proximity:{balanced:[{minimum_neighbours:15,rank:1,reverse_rank:15}]}} as GraphData;
  expect(connectionDistance(distant,drawing,node,'balanced','6')).toContain('Above the current setting limit of 10');
});
test('hover separates score shortfall from neighbour ranks without inventing data',()=>{
  const below={...data,connection_proximity:undefined};
  expect(connectionDistance(below,drawing,node,'balanced','6',[{id:'b',balanced:.84,profile:.6,source:.6}])).toContain('cutoff: 0.8500 (gap 0.0100)');
  expect(connectionDistance(below,drawing,node,'balanced','6',[{id:'b',balanced:.9,profile:.3,source:.3}])).toContain('raw score is 0.3000');
  expect(connectionDistance(below,drawing,node,'balanced','6',[{id:'b',balanced:.9,profile:.6,source:.6}])).toBeNull();
  expect(connectionDistance(below,drawing,node,'balanced','6',[])).toBeNull();
  expect(connectionDistance(below,drawing,node,'balanced','6')).toBeNull();
});
