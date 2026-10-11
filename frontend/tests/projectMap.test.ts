import {describe,expect,test} from 'bun:test';
import cytoscape from 'cytoscape';
import {emptyFilters,facetCounts,londonToday,matches,projectIdMatches,sizeFor} from '../src/projectMap/filters';
import type {ProjectNode} from '../src/projectMap/types';
import {buildStatusColours} from '../src/projectMap/colours';
import {connectedProjects} from '../src/projectMap/connections';
const p=(extra:Partial<ProjectNode>={}):ProjectNode=>({id:'a',title:'Battery research',reference:'SAME',owner:'Distribution',status:'Live',funding:['NIA'],technology:['Storage','Control'],themes:[],research:[],start_date:'2026-01-01',end_date:'2026-06-01',invalid_dates:false,flags:[],preceding:[],...extra}as ProjectNode);
describe('source-backed map filters',()=>{
  test('status colours include arbitrary source values without inventing statuses',()=>{
    const statuses=['Live','Complete','Paused','Planned','Cancelled','constructor',''];
    const colours=buildStatusColours(statuses);
    expect(Object.keys(colours).sort()).toEqual(['Live','Complete','Paused','Planned','Cancelled','constructor','Not recorded'].sort());
    expect(new Set(Object.values(colours)).size).toBe(statuses.length);
    expect(buildStatusColours([...statuses].reverse())).toEqual(colours);
    expect(buildStatusColours(['Complete']).Complete).toBe(colours.Complete);
    const graph=cytoscape({headless:true,styleEnabled:true,elements:Object.entries(colours).map(([id,colour])=>({data:{id,colour}})),style:[{selector:'node',style:{'background-color':'data(colour)'}}]});
    try{expect(new Set(graph.nodes().map(node=>node.style('background-color'))).size).toBe(statuses.length)}finally{graph.destroy()}
  });
  test('connections require both endpoints in filters and count enabled relationship types',()=>{
    const nodes=[p({id:'a'}),p({id:'b'}),p({id:'c'}),p({id:'d'})];
    const edges=[[0,1,.9],[1,2,.8]];
    const lineage=[{source:'c',target:'d',reference:'prev',field:'PRECEDING PROJECTS'}];
    const all=new Set(nodes.map(n=>n.id));
    expect([...connectedProjects(nodes,edges,lineage,all,true,false)].sort()).toEqual(['a','b','c']);
    expect([...connectedProjects(nodes,edges,lineage,new Set(['a','c','d']),true,false)]).toEqual([]);
    expect([...connectedProjects(nodes,edges,lineage,all,false,true)].sort()).toEqual(['c','d']);
    expect([...connectedProjects(nodes,edges,lineage,all,true,true)].sort()).toEqual(['a','b','c','d']);
    expect([...connectedProjects(nodes,[],[{...lineage[0],source:'d'}],all,false,true)]).toEqual([]);
  });
  test('ID jump uses exact GUID or reference and preserves ambiguous entries',()=>{
    const nodes=[p({id:'guid-A',reference:'NIA_SPEN_001'}),p({id:'guid-B',reference:'IFI 0621'}),p({id:'guid-C',reference:'IFI 0621'})];
    expect(projectIdMatches(nodes,' GUID-a ')).toEqual([nodes[0]]);
    expect(projectIdMatches(nodes,'nia_spen_001')).toEqual([nodes[0]]);
    expect(projectIdMatches(nodes,'ifi0621')).toEqual(nodes.slice(1));
    expect(projectIdMatches(nodes,'NIA_SPEN_00')).toEqual([]);
    expect(projectIdMatches(nodes,' ')).toEqual([]);
  });
  test('no filters includes missing fields and duplicate references',()=>{const f=emptyFilters();expect([p(),p({id:'b',end_date:null}),p({id:'c',flags:['Apparent test record']})].filter(n=>matches(n,f))).toHaveLength(3)});
  test('OR within facets, AND between facets',()=>{const f=emptyFilters();f.facets.technology=['Storage','Comms'];f.facets.funding=['SIF'];expect(matches(p(),f)).toBe(false);expect(matches(p({funding:['SIF']}),f)).toBe(true)});
  test('Live status is distinct from activity by dates',()=>{const f=emptyFilters();f.live='yes';expect(matches(p(),f)).toBe(true);f.dateMode='active';f.asof='2026-10-10';expect(matches(p(),f)).toBe(false)});
  test('unknown dates explicit; inclusive boundaries; invalid ranges',()=>{const f=emptyFilters();f.dateMode='active';f.asof='2026-06-01';expect(matches(p(),f)).toBe(true);expect(matches(p({end_date:null}),f)).toBe(false);f.unknownEnd=true;expect(matches(p({end_date:null}),f)).toBe(true);expect(matches(p({invalid_dates:true}),f)).toBe(false);f.dateMode='overlap';f.from='2026-07-01';f.to='2026-06-01';expect(matches(p(),f)).toBe(false)});
  test('missing categories and selected zero counts remain removable',()=>{const f=emptyFilters();f.facets.research=['Not recorded'];expect(matches(p(),f)).toBe(true);f.facets.research=['Absent category'];expect(facetCounts([p()],f,'research')).toContainEqual(['Absent category',0])});
  test('Today tracks UK midnight and daylight saving transitions',()=>{expect(londonToday(new Date('2026-10-09T23:30:00Z'))).toBe('2026-10-10');expect(londonToday(new Date('2026-10-25T00:30:00Z'))).toBe('2026-10-25');expect(londonToday(new Date('2026-10-25T23:30:00Z'))).toBe('2026-10-25')});
  test('date range uses source dates and no implicit infinite end',()=>{const f=emptyFilters();f.dateMode='overlap';f.from='2026-06-01';f.to='2026-10-01';expect(matches(p(),f)).toBe(true);expect(matches(p({end_date:null}),f)).toBe(false);f.dateMode='start';f.from='2026-01-02';expect(matches(p(),f)).toBe(false)});
  test('financial areas are proportional and do not depend on filters',()=>{const small=sizeFor(100000,1000000,false),large=sizeFor(1000000,1000000,false);expect(large**2/small**2).toBeCloseTo(10);expect(sizeFor(null,1000000,false)).toBe(12);expect(sizeFor(0,1000000,false)).toBe(3)});
});
