import type {Core} from 'cytoscape';
export function overviewZoom(width:number,height:number,bounds:{w:number;h:number},padding=60){
  return Math.max(.000001,Math.min(1.4,Math.max(1,width-2*padding)/Math.max(1,bounds.w),Math.max(1,height-2*padding)/Math.max(1,bounds.h)));
}
export function limitToVisibleProjects(graph:Core,fit=false){
  const shown=graph.nodes(':visible');if(!shown.length)return graph.minZoom();
  const bounds=shown.boundingBox({includeLabels:false}),minimum=overviewZoom(graph.width(),graph.height(),bounds);
  graph.minZoom(minimum);
  if(fit||graph.zoom()<minimum){graph.viewport({zoom:minimum,pan:{x:(graph.width()-minimum*(bounds.x1+bounds.x2))/2,y:(graph.height()-minimum*(bounds.y1+bounds.y2))/2}})}
  return minimum;
}
export function statusShape(status:string){return status==='Live'?'diamond':status==='Complete'?'ellipse':'rectangle'}
// Keep filled area proportional to investment even though status changes shape.
export function statusSizeFactor(status:string){return status==='Live'?Math.sqrt(Math.PI/2):status==='Complete'?1:Math.sqrt(Math.PI)/2}
