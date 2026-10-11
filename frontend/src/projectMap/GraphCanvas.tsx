import {useEffect,useRef,useState} from 'react';
import cytoscape from 'cytoscape';
import type {Core,ElementDefinition} from 'cytoscape';
import {Maximize,Maximize2,Minimize,Minus,Plus} from 'lucide-react';
import type {Drawing,FocusRequest,GraphData,Lens,Match,Measure,ProjectNode} from './types';
import type {MapSource} from './mapData';
import {connectionDistance,connectionExplanation,hoverGroup} from './hoverDetails';
import {compactMoney,dateLabel,sizeFor} from './filters';

import {limitToVisibleProjects,statusShape,statusSizeFactor} from './viewport';
import {projectColour} from './colours';

function focusProject(graph:Core,id:string){
  const node=graph.getElementById(id);
  if(node.empty()||!node.visible())return false;
  graph.zoom(Math.max(1.1,graph.zoom()));graph.center(node);return true;
}
type Props={source:MapSource;data:GraphData;layout:Drawing;linkKey:string;focusRequest:FocusRequest|null;lens:Lens;measure:Measure;equalSize:boolean;compressed:boolean;colour:string;statusColours:Record<string,string>;groupColours:Record<number,string>;visible:Set<string>;selected:string;view:string;showLinks:boolean;showLineage:boolean;onSelect:(id:string)=>void};
export default function GraphCanvas(p:Props){
  const container=useRef<HTMLDivElement>(null),cy=useRef<Core|null>(null),callback=useRef(p.onSelect);
  const shell=useRef<HTMLDivElement>(null),fullscreenButton=useRef<HTMLButtonElement>(null);
  const[fullscreen,setFullscreen]=useState(false);
  const[hover,setHover]=useState<ProjectNode|null>(null),[zoom,setZoom]=useState(1),[minimumZoom,setMinimumZoom]=useState(0);
  const[hoverScores,setHoverScores]=useState<{id:string;revision:string;lens:Lens;matches:Match[]}|null>(null);
  callback.current=id=>{
    setHover(null);
    if(!fullscreen){p.onSelect(id);return}
    const finish=()=>{setFullscreen(false);requestAnimationFrame(()=>p.onSelect(id))};
    if(document.fullscreenElement===shell.current)void document.exitFullscreen().catch(()=>{}).finally(finish);
    else finish();
  };
  const nodesRef=useRef(p.data.nodes);nodesRef.current=p.data.nodes;
  const focusRef=useRef(p.focusRequest);focusRef.current=p.focusRequest;
  const previous=useRef('');
  const hoverIndex=hover?p.data.nodes.findIndex(n=>n.id===hover.id):-1;
  const hoverIsolated=p.layout.isolated.includes(hoverIndex);
  useEffect(()=>{
    setHoverScores(null);
    if(!hover||!hoverIsolated)return;
    const ctrl=new AbortController();
    // Only read the small, saved comparison row for an unlinked hovered project.
    const timer=setTimeout(()=>{p.source.neighbours(p.data,hover.id,p.lens,ctrl.signal).then(result=>{
      if(!ctrl.signal.aborted&&result.revision===p.data.revision)setHoverScores({id:hover.id,revision:result.revision,lens:p.lens,matches:result.matches});
    }).catch(()=>{/* The immediate explanation remains available if a row cannot load. */})},120);
    return()=>{clearTimeout(timer);ctrl.abort()};
  },[hover?.id,hoverIsolated,p.data.revision,p.lens,p.source]);
  useEffect(()=>{setHover(null)},[p.layout,p.visible]);
  const group=hover?hoverGroup(p.layout,hoverIndex):null;
  const matches=hover&&hoverScores?.id===hover.id&&hoverScores.revision===p.data.revision&&hoverScores.lens===p.lens?hoverScores.matches:undefined;
  const explanation=hover&&p.view!=='lineage'?connectionExplanation(p.data,p.layout,hover,p.lens,p.visible,matches):null;
  const distance=hover&&p.view!=='lineage'?connectionDistance(p.data,p.layout,hover,p.lens,p.linkKey,matches):null;
  useEffect(()=>{
    if(!fullscreen)return;
    const previousFocus=document.activeElement as HTMLElement|null,previousOverflow=document.body.style.overflow;
    document.body.style.overflow='hidden';fullscreenButton.current?.focus();
    const escape=(event:KeyboardEvent)=>{if(event.key==='Escape')setFullscreen(false)};
    const changed=()=>{if(document.fullscreenElement!==shell.current)setFullscreen(false)};
    document.addEventListener('keydown',escape);document.addEventListener('fullscreenchange',changed);
    return()=>{
      document.body.style.overflow=previousOverflow;
      document.removeEventListener('keydown',escape);document.removeEventListener('fullscreenchange',changed);
      if(document.fullscreenElement===shell.current)void document.exitFullscreen().catch(()=>{});
      previousFocus?.focus();
    };
  },[fullscreen]);
  function toggleFullscreen(){
    if(fullscreen){setFullscreen(false);return}
    setFullscreen(true);
    // Embedded browsers may deny native fullscreen; the viewport-sized view still works.
    if(shell.current?.requestFullscreen)void shell.current.requestFullscreen().catch(()=>{});
  }
  useEffect(()=>{
    if(!container.current)return;
    const graph=cytoscape({container:container.current,elements:[],minZoom:.000001,maxZoom:4,pixelRatio:Math.min(window.devicePixelRatio||1,2),selectionType:'single',boxSelectionEnabled:false,
      style:[
        {selector:'node',style:{'background-color':'data(colour)','background-opacity':1,width:'data(size)',height:'data(size)',shape:node=>statusShape(node.data('status')),'border-color':'data(colour)','border-width':1,'label':'','text-events':'yes','font-family':'Arial','font-size':14,'color':'#173b51','text-wrap':'wrap','text-max-width':'190px','text-valign':'bottom','text-margin-y':10,'text-background-color':'#fff','text-background-opacity':.92,'text-background-padding':'5px','underlay-color':'data(colour)','underlay-opacity':.16,'underlay-padding':7}},
        {selector:'node.unknown',style:{'background-opacity':0,'border-style':'dashed','border-width':2}},
        {selector:'node.focused, node.hovered',style:{'border-color':'#183e53','border-width':3,'label':'data(title)','z-index':25,'underlay-color':'#d49c32','underlay-opacity':.22,'underlay-padding':10}},
        {selector:'node.lineage-node',style:{label:'data(reference)','text-events':'yes'}},
        {selector:'node.dim',style:{opacity:.5}},
        {selector:'edge',style:{'width':1.2,'line-color':'#a8bbc4','opacity':.3,'curve-style':'straight','events':'no'}},
        {selector:'edge.lineage',style:{'line-color':'#ce8c31','line-style':'dashed','target-arrow-shape':'triangle','target-arrow-color':'#ce8c31',width:2,opacity:.8,'curve-style':'bezier'}},
        {selector:'edge.highlighted',style:{'line-color':'#306a7f',width:2,opacity:.85,'z-index':15}},
        {selector:'.hidden',style:{display:'none'}}
      ]});
    cy.current=graph;
    graph.on('tap','node',e=>callback.current(e.target.id()));
    graph.on('tap',e=>{if(e.target!==graph)return;const p=e.renderedPosition;let nearest:string|undefined,best=81;graph.nodes(':visible').forEach(n=>{const q=n.renderedPosition(),d=(p.x-q.x)**2+(p.y-q.y)**2;if(d<best){best=d;nearest=n.id()}});if(nearest)callback.current(nearest)});
    graph.on('mouseover','node',e=>{e.target.addClass('hovered');setHover(nodesRef.current.find(n=>n.id===e.target.id())||null)});
    graph.on('mouseout','node',e=>{e.target.removeClass('hovered');setHover(null)});
    graph.on('zoom',()=>{if(graph.zoom()<=graph.minZoom()+1e-6)graph.center(graph.nodes(':visible'))});
    graph.on('zoom',()=>setZoom(graph.zoom()));
    const observer=new ResizeObserver(()=>{graph.resize();setMinimumZoom(limitToVisibleProjects(graph,true));if(focusRef.current)focusProject(graph,focusRef.current.id)});observer.observe(container.current);
    return()=>{observer.disconnect();graph.destroy();cy.current=null};
  },[p.data.revision]);
  useEffect(()=>{
    const graph=cy.current;if(!graph)return;
    const layout=p.layout,max=Math.max(1,...p.data.nodes.map(n=>n.money[p.measure].value||0));
    const key=`${p.data.revision}:${p.lens}:${p.linkKey}:${p.view==='lineage'?'lineage':'map'}`;
    const isNew=key!==previous.current;
    const selectedNeighbours=new Set<string>();
    for(const [a,b]of layout.edges){if(p.data.nodes[a].id===p.selected)selectedNeighbours.add(p.data.nodes[b].id);if(p.data.nodes[b].id===p.selected)selectedNeighbours.add(p.data.nodes[a].id)}
    graph.batch(()=>{
      if(isNew){
        graph.elements().remove();
        const elements:ElementDefinition[]=p.data.nodes.map((n,i)=>({data:{id:n.id,title:n.title,reference:n.reference||n.title,colour:projectColour(n,p.colour,layout.groups[i],p.statusColours,p.groupColours),status:n.status,size:(p.equalSize?18:sizeFor(n.money[p.measure].value,max,p.compressed))*statusSizeFactor(n.status)},position:{x:(p.view==='lineage'?p.data.lineage_positions:layout.positions)[i][0],y:(p.view==='lineage'?p.data.lineage_positions:layout.positions)[i][1]}}));
        for(const[a,b,score]of layout.edges)elements.push({data:{id:`sim-${a}-${b}`,source:p.data.nodes[a].id,target:p.data.nodes[b].id,score},classes:'similarity'});
        for(const[e,i]of p.data.lineage.map((e,i)=>[e,i]as const))elements.push({data:{id:`lin-${i}`,source:e.source,target:e.target},classes:'lineage'});
        graph.add(elements);previous.current=key;
      }
      for(const[n,i]of p.data.nodes.map((n,i)=>[n,i]as const)){
        const node=graph.getElementById(n.id);
        node.data({colour:projectColour(n,p.colour,layout.groups[i],p.statusColours,p.groupColours),status:n.status,size:(p.equalSize?18:sizeFor(n.money[p.measure].value,max,p.compressed))*statusSizeFactor(n.status)});
        node.toggleClass('hidden',!p.visible.has(n.id));node.toggleClass('unknown',!p.equalSize&&n.money[p.measure].value===null);
        node.toggleClass('focused',n.id===p.selected);node.toggleClass('lineage-node',p.view==='lineage');node.toggleClass('dim',p.visible.has(p.selected)&&n.id!==p.selected&&!selectedNeighbours.has(n.id)&&p.view!=='lineage');
      }
      graph.edges().forEach(edge=>{
        const semantic=edge.hasClass('similarity'),connected=edge.source().id()===p.selected||edge.target().id()===p.selected;
        const shown=p.visible.has(edge.source().id())&&p.visible.has(edge.target().id())&&(semantic?p.view!=='lineage'&&(p.showLinks||connected):p.showLineage||p.view==='lineage');
        edge.toggleClass('hidden',!shown);edge.toggleClass('highlighted',semantic&&connected);
      });
    });
    setMinimumZoom(limitToVisibleProjects(graph,isNew||p.visible.size<2));
  },[p.data,p.layout,p.linkKey,p.lens,p.measure,p.equalSize,p.compressed,p.colour,p.statusColours,p.groupColours,p.visible,p.selected,p.view,p.showLinks,p.showLineage]);
  useEffect(()=>{
    if(!p.focusRequest)return;
    const id=p.focusRequest.id;
    const frame=requestAnimationFrame(()=>{
      const graph=cy.current;if(!graph)return;
      if(id)focusProject(graph,id);
      else setMinimumZoom(limitToVisibleProjects(graph,true));
    });
    return()=>cancelAnimationFrame(frame);
  },[p.focusRequest]);
  useEffect(()=>{if(p.view==='lineage'&&cy.current&&p.visible.size){setMinimumZoom(limitToVisibleProjects(cy.current,true))}},[p.view,p.visible]);
  function fit(){const graph=cy.current;if(graph)setMinimumZoom(limitToVisibleProjects(graph,true))}
  function scale(factor:number){const graph=cy.current;if(graph)graph.zoom({level:Math.min(4,Math.max(graph.minZoom(),graph.zoom()*factor)),renderedPosition:{x:graph.width()/2,y:graph.height()/2}})}
  return <div ref={shell} className={`map-canvas-shell${fullscreen?' is-fullscreen':''}`}>
    <div ref={container} className="map-canvas" role="img" aria-label={`${p.visible.size} project bubbles. Diamond = source says Live; circle = Complete; square = other or unrecorded status. Use the matching project table for keyboard navigation.`}/>
    {!p.visible.size&&<div className="map-empty"><strong>No projects in this view</strong><span>Clear a filter or choose Portfolio to see all matching projects.</span></div>}
    <div className="map-zoom"><button aria-label="Zoom in" onClick={()=>scale(1.4)}><Plus size={17}/></button><button aria-label="Zoom out" disabled={zoom<=minimumZoom+1e-6} title="Zoom out to show all visible projects" onClick={()=>scale(1/1.4)}><Minus size={17}/></button><button aria-label="Fit visible projects" onClick={fit}><Maximize2 size={17}/></button><button ref={fullscreenButton} aria-label={fullscreen?'Exit full screen map':'Full screen map'} title={fullscreen?'Exit full screen (Esc)':'Full screen map'} aria-pressed={fullscreen} onClick={toggleFullscreen}>{fullscreen?<Minimize size={17}/>:<Maximize size={17}/>}</button></div>
    {!p.equalSize&&<div className="map-size-legend"><span>{p.data.financial_measures.find(m=>m.id===p.measure)?.label} · {p.compressed?'compressed scale':'proportional area'}</span><div>{[100000,1000000,10000000].map(value=><div key={value}><i style={{borderWidth:zoom,width:sizeFor(value,Math.max(1,...p.data.nodes.map(n=>n.money[p.measure].value||0)),p.compressed)*zoom,height:sizeFor(value,Math.max(1,...p.data.nodes.map(n=>n.money[p.measure].value||0)),p.compressed)*zoom}}/><small>{compactMoney(value)}</small></div>)}</div><small>Equal investment = equal filled area across shapes. Hollow = amount not recorded. Legend follows zoom.</small></div>}
    {p.equalSize&&<div className="map-size-legend"><span>Equal-size projects</span><small>Every entry has the same size. Choose investment sizes to compare recorded amounts.</small></div>}
    {!hover&&<div className="map-status-legend" aria-label="Project status shapes"><b>Source status · shape</b>{Object.keys(p.statusColours).map(status=><span key={status}><i className={statusShape(status)}/>{status}</span>)}</div>}
    <div className="map-edge-legend"><span><i/>Similarity</span><span><i className="lineage"/>Predecessor → successor</span><small>{Math.round(zoom*100)}% zoom</small></div>
    {hover&&<div className="map-hover" role="status"><strong>{hover.title}</strong><span>{hover.reference||'Reference not supplied'} · {hover.status}</span><span>Start date · {dateLabel(hover.start_date)}</span>{(hover.status==='Complete'||hover.status==='Live'&&hover.end_date)&&<span>End date · {dateLabel(hover.end_date)}</span>}{group&&<span className="map-hover-group"><i style={{background:p.groupColours[group.id]}}/>{group.label}</span>}<span>{hover.money[p.measure].value===null?'Amount not recorded':compactMoney(hover.money[p.measure].value!)} · {hover.money[p.measure].label}</span>{explanation&&<p className="map-hover-explanation">{explanation}{distance&&<span className="map-hover-distance">{distance}</span>}{hoverIsolated&&<small>No link does not mean there is no related work.</small>}</p>}{!explanation&&!p.showLinks&&hover.id!==p.selected&&p.view!=='lineage'&&<p className="map-hover-explanation">Similarity lines are switched off.</p>}</div>}
  </div>;
}
