"""Validated internal Luna facts for large/1024 search; never report evidence."""
import copy
import json
import re
from pathlib import Path

from core.retrieval_summary import build_request as selected_input, METADATA
from core.text import digest

RECIPE = 'luna-search-profile-v3'
REASONING_EFFORT = 'medium'
MAX_OUTPUT_TOKENS = 8192
SYSTEM = Path(__file__).with_name('retrieval_profile_prompt.txt').read_text() + '''
Use brief contiguous exact quotes, preferably 5–30 words; no ellipses, paraphrases or corrected spelling inside quotes. Aim for a rendered fact body of about 150–250 words for a rich project, without sacrificing its central technical distinctions. Preserve every supported must_retain_term in a factual statement, rather than a disconnected list. Do not repeat the title in facts.'''
SCHEMA = json.loads(Path(__file__).with_name('retrieval_profile_schema.json').read_text())
USEFUL_METADATA = {'researchAreas','technologyAreas','leadSector','scaleOfProject','geographicalArea',
    'techReadinessAtStart','techReadinessAtEnd','precedingProjects','addPrecedingProjects',
    'associatedInnovationProjects','projectDurationMonths'}
EMPTY = {'true','false','na','n/a','none','not applicable','-','[]','{}'}
GENERIC_ACRONYMS = {'SPEN','SPT','SPD','SP','UK','GB','NIA','SIF','RIIO','ED','ED1','ED2','ED3',
    'DNO','DNOs','DSO','TO','TNO','BAU','IPR','R&D','WP','KPI','ENA','EU','TRL','NGET','NG','WPD',
    'SSE','UKPN','ENWL','UoS','NPG','KTP','NT','NI','AND','THE','NA','NONE'}
PATTERNS = (
    re.compile(r'\b(?:IEC|ISO|BS|IEEE|EN)\s*\d{3,6}(?:[-:]\d{1,4})*\b'),
    re.compile(r'(?<![\w.])\d+(?:\.\d+)?\s*(?:kV|kVA|MVA|MW|kW|MHz|GHz|Hz|kWh|MWh|mm|MPa|bar)\b'),
    re.compile(r'\b(?:[A-Z][A-Z0-9]{1,9}(?:-[A-Z0-9]+)?|LiDAR|STATCOM|g3|SF6|V2G)\b'))


def eligible(text):
    return bool(text.strip()) and text.strip().casefold().rstrip('.') not in EMPTY


def term_candidates(passages):
    """Source-only technical identifiers, independent of evaluation queries/labels."""
    candidates=[]; seen=set()
    narratives=[p for p in passages if not p['id'].startswith('metadata:')]
    for pattern in PATTERNS:
        for p in narratives:
            for match in pattern.finditer(p['text']):
                term=match.group(); key=canonical(term)
                if term in GENERIC_ACRONYMS or re.fullmatch(r'[A-Z]{2}-[A-Z]{2}',term) or key in seen:continue
                seen.add(key);candidates.append(term)
                if len(candidates)==8:return candidates
    return candidates


def request_for(store, project):
    original=selected_input(store,project)
    passages=[dict(p) for p in original['passages'] if eligible(p['text'])]
    for field,value in original['metadata'].items():
        if field in USEFUL_METADATA and eligible(value):
            passages.append({'id':'metadata:'+field,'field':field,'text':value})
    overrides=store.meta('retrieval_term_overrides') or {}
    candidates=overrides.get(project['id'],term_candidates(passages))
    terms=[]
    for candidate in candidates:
        pattern=re.compile(r'(?<!\w)'+re.escape(candidate)+r'(?!\w)',re.I)
        source=next((p for p in passages if pattern.search(p['text'])),None)
        if source is None:continue
        match=pattern.search(source['text']);exact=source['text'][match.start():match.end()]
        quote=source['text'][max(0,match.start()-45):min(len(source['text']),match.end()+70)]
        terms.append({'term':exact,'evidence':[{'source_id':source['id'],'quote':quote}]})
    return {'purpose':'Internal embedding profile only; never displayed to users',
        'title':project['title'],'reference':project['reference'],'embedding_model':'text-embedding-3-large',
        'embedding_dimensions':1024,'passages':passages,'must_retain_terms':terms,'approved_aliases':[],
        'source_truncated':original['source_truncated'],'omissions':original['omissions']}


def canonical(text):
    return ''.join(c for c in text.casefold() if not c.isspace())


def render(profile):
    labels={'problem':'Problem','method':'Method','asset_technology':'Technology',
        'application_population':'Application','technical_parameter':'Technical parameter',
        'scope_phase':'Scope','reported_result':'Result'}
    return '\n'.join(f"{labels[f['aspect']]} ({f['state']}): {f['text']}" for f in profile['facts'])


def validate(profile, request, reviewed_variants=None):
    import jsonschema
    jsonschema.validate(profile,SCHEMA)
    sources={p['id']:p['text'] for p in request['passages']}
    aliases={a['id'] for a in request['approved_aliases']}
    for item in profile['facts']+profile['protected_terms']+profile['conflicts']:
        for e in item['evidence']:
            if e['source_id'] not in sources or e['quote'] not in sources[e['source_id']]:
                raise ValueError('Invalid source ID or non-exact supporting quote')
    for fact in profile['facts']:
        if any(a not in aliases for a in fact['approved_alias_ids']):raise ValueError('Unapproved alias')
    for term in profile['protected_terms']:
        if not any(canonical(term['term']) in canonical(e['quote']) for e in term['evidence']):
            raise ValueError('Protected term absent from supporting quote')
    body=render(profile); variants=reviewed_variants or {}
    missing=[t['term'] for t in request['must_retain_terms'] if canonical(t['term']) not in canonical(body)
        and not any(canonical(v) in canonical(body) for v in variants.get(t['term'],[]))]
    if missing:raise ValueError('Must-retain terms missing from embedded facts: '+', '.join(missing))
    if not body.strip():raise ValueError('No supported profile facts')
    if len(body.encode())>14000:raise ValueError('Profile too long for embedding input')
    return body


def repair_orthography(profile, request):
    """Repair citation case/whitespace only; preserve fact words and an audit trail."""
    profile=copy.deepcopy(profile); sources={p['id']:p['text'] for p in request['passages']};repairs=[]
    for section in ('facts','protected_terms','conflicts'):
        for item in profile.get(section,[]):
            for evidence in item.get('evidence',[]):
                if evidence.get('source_id') in sources and evidence.get('quote','') in sources[evidence['source_id']]:continue
                target=canonical(evidence.get('quote',''))
                if not target:continue
                hits=[]
                for sid,text in sources.items():
                    chars=[];offsets=[]
                    for i,char in enumerate(text):
                        if not char.isspace():
                            for c in char.casefold():chars.append(c);offsets.append(i)
                    start=''.join(chars).find(target)
                    if start>=0:hits.append((sid,text[offsets[start]:offsets[start+len(target)-1]+1]))
                same=[h for h in hits if h[0]==evidence.get('source_id')]
                if same:hits=same
                if len(hits)==1:
                    before=dict(evidence);evidence['source_id'],evidence['quote']=hits[0]
                    repairs.append({'before':before,'after':dict(evidence),'rule':'Case/whitespace only; fact text unchanged'})
    return profile,repairs


def summary_record(profile,request,body,generation=None,attempts=None,repairs=None):
    return {'summary':body,'profile':profile,'profile_request':request,'prompt_version':RECIPE,
        'generation':generation or {},'attempts':attempts or [],'citation_repairs':repairs or [],
        'missing_evidence':profile['missing_evidence'],'source_truncated':request['source_truncated'],
        'embedding_target':{'model':'text-embedding-3-large','dimensions':1024},'internal_only':True}


def validation_feedback(profile,request,message):
    sources={p['id']:p['text'] for p in request['passages']};invalid=[];term_evidence=[]
    for section in ('facts','protected_terms','conflicts'):
        for i,item in enumerate(profile.get(section,[])):
            for j,e in enumerate(item.get('evidence',[])):
                if e.get('source_id') not in sources or e.get('quote','') not in sources[e['source_id']]:
                    invalid.append({'path':f'{section}[{i}].evidence[{j}]',**e})
    for i,t in enumerate(profile.get('protected_terms',[])):
        if not any(canonical(t.get('term','')) in canonical(e.get('quote','')) for e in t.get('evidence',[])):
            term_evidence.append({'path':f'protected_terms[{i}]','term':t.get('term')})
    body=render(profile)
    missing=[t['term'] for t in request['must_retain_terms'] if canonical(t['term']) not in canonical(body)]
    return {'message':message,'non_exact_citations':invalid,'protected_terms_without_matching_quote':term_evidence,
        'terms_missing_from_embedded_facts':missing,
        'instruction':'Copy contiguous original source text exactly, including punctuation. Required technical terms belong in facts, not only the protected_terms list.'}


def generate_summary(model,request,purpose='project search profile'):
    attempts=[]; feedback=None;previous=None
    for attempt in range(3):
        data=request if feedback is None else {**request,'validation_feedback':feedback,'previous_output':previous,
            'repair_instruction':'Correct the validation error using the supplied original passages only. Return the complete schema.'}
        # Transport errors propagate immediately; this loop corrects completed but invalid outputs only.
        profile=model.structured(SYSTEM,data,SCHEMA,purpose,max_output=MAX_OUTPUT_TOKENS,reasoning_effort=REASONING_EFFORT)
        generation=copy.deepcopy(getattr(model,'last_generation',{}))
        repaired,repairs=repair_orthography(profile,request)
        try:
            body=validate(repaired,request)
        except ValueError as error:
            attempts.append({'generation':generation,'raw_profile':profile,'validation_error':str(error)})
            feedback=validation_feedback(repaired,request,str(error));previous=profile
            continue
        attempts.append({'generation':generation,'raw_profile':profile,'validation_error':None})
        return summary_record(repaired,request,body,generation,attempts,repairs)
    raise ValueError('Profile validation failed after three completed outputs: '+str(feedback))


def source_hash(store,project):
    prompt=SYSTEM+REASONING_EFFORT+json.dumps(SCHEMA,sort_keys=True)
    raw=project.get('raw_fields') or {}
    metadata={key:raw.get(label,raw.get(key)) for key,label in METADATA.items() if key in USEFUL_METADATA}
    override=(store.meta('retrieval_term_overrides') or {}).get(project['id'])
    signature=digest(json.dumps([project['id'],project.get('semantic_hash'),project['title'],project['reference'],
        metadata,project.get('technology'),override,digest(prompt),sorted(GENERIC_ACRONYMS)],sort_keys=True,ensure_ascii=False))
    # Source revisions and useful metadata invalidate this cache across imports;
    # overrides are re-read so an external Store cannot leave stale term policy.
    with store._profile_hash_lock:
        if signature in store._profile_hash_cache:return store._profile_hash_cache[signature]
    value=digest(prompt+json.dumps(request_for(store,project),sort_keys=True,ensure_ascii=False))
    with store._profile_hash_lock:
        if len(store._profile_hash_cache)>1024:store._profile_hash_cache.clear()
        store._profile_hash_cache[signature]=value
    return value
