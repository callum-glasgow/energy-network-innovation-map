import {useEffect,useState} from 'react';
import type {Pair} from './types';
export function PairReview({pair}:{pair:Pair}){
  const key=`innovation-map-review:${pair.revision}:${pair.a}:${pair.b}`;
  const[grade,setGrade]=useState(''),[reason,setReason]=useState(''),[status,setStatus]=useState('');
  useEffect(()=>{setStatus('');setGrade('');setReason('');try{const saved=JSON.parse(localStorage.getItem(key)||'null');if(saved){setGrade(saved.grade||'');setReason(saved.reason||'')}}catch{setStatus('Browser storage is unavailable. You can still export a review.')}},[key]);
  function record(){return {revision:pair.revision,a:pair.a,b:pair.b,grade,reason,reviewed_at:new Date().toISOString()}}
  function save(){try{localStorage.setItem(key,JSON.stringify(record()));setStatus('Saved in this browser.')}catch{setStatus('Could not save in this browser. Export the review instead.')}}
  function download(){const url=URL.createObjectURL(new Blob([JSON.stringify(record(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='project-relationship-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
  return <details className="map-pair-review"><summary>Record your assessment</summary><p>Your review is stored in this browser and can be exported with the snapshot revision.</p><label>Relationship<select aria-label="Reviewed relationship" value={grade} onChange={e=>setGrade(e.target.value)}><option value="">Choose an assessment</option><option>Directly reusable learning</option><option>Related background</option><option>Superficially similar</option><option>Unrelated</option><option>Insufficient evidence</option></select></label><label>Reason<textarea aria-label="Relationship review reason" rows={3} maxLength={4000} value={reason} onChange={e=>setReason(e.target.value)}/></label><button className="secondary" disabled={!grade} onClick={save}>Save review</button><button className="secondary" disabled={!grade} onClick={download}>Export review</button>{status&&<p role="status">{status}</p>}</details>
}
