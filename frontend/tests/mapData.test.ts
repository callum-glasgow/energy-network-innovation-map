import {test,expect} from 'bun:test';
import {decodeRow,rowScores,StaticMapSource} from '../src/projectMap/mapData';
import type {GraphData} from '../src/projectMap/types';
test('portable little-endian scores preserve missing channels and reject truncated rows',()=>{
  const buffer=new ArrayBuffer(72),view=new DataView(buffer);
  [.9,NaN,.4,.1,.2,.3].forEach((v,i)=>view.setFloat32(i*4,v,true));
  const row=decodeRow(buffer,2);
  expect(rowScores(row,0).balanced).toBeCloseTo(.9);expect(rowScores(row,0).profile).toBeNull();expect(rowScores(row,1).source).toBeCloseTo(.3);
  expect(()=>decodeRow(buffer.slice(0,60),2)).toThrow('Incomplete');
});
test('static map resolves assets below a repository path and restores original pair evidence',async()=>{
  const buffer=new ArrayBuffer(72),view=new DataView(buffer);
  [.9,.8,.7,.6,.5,.4].forEach((v,i)=>view.setFloat32(i*4,v,true));
  for(let i=24;i<72;i+=4)view.setInt32(i,-1,true);
  view.setInt32(48,10,true);view.setInt32(52,20,true);
  const urls:string[]=[],original=globalThis.fetch;
  globalThis.fetch=(async(input:RequestInfo|URL)=>{const url=String(input);urls.push(url);if(url.endsWith('.bin'))return new Response(buffer);return Response.json(url.endsWith('projects/0.json')?{revision:'r',passages:{'10':{field:'method',source_id:'pa',text:'Original A'}}}:{revision:'r',passages:{'20':{field:'method',source_id:'pb',text:'Original B'}}})}) as typeof fetch;
  try{
    const source=new StaticMapSource(new URL('https://example.github.io/repository/data/'));
    const data={revision:'r',snapshot:{format:1,root:'r/'},nodes:[{id:'a',technology:['X'],themes:[],research:[],funding:[]},{id:'b',technology:['X','Y'],themes:[],research:[],funding:[]}]} as unknown as GraphData;
    const pair=await source.pair(data,'a','b');
    expect(pair.evidence[0].a.text).toBe('Original A');expect(pair.evidence[0].b.text).toBe('Original B');expect(pair.shared.technology).toEqual(['X']);expect(pair.different.technology.b).toEqual(['Y']);
    expect(urls.every(url=>url.startsWith('https://example.github.io/repository/data/r/'))).toBe(true);
    expect((await source.neighbours(data,'a','balanced')).matches).toHaveLength(1);
    expect(urls.filter(u=>u.endsWith('.bin'))).toHaveLength(1);
  }finally{globalThis.fetch=original}
});
