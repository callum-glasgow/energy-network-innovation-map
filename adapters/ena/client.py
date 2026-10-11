import csv
import io
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from core.config import ORIGIN, OWNERS, DATA, ROOT
from core.storage import now
from core.text import clean, link
from core.retrieval_summary import PRIMARY, CONTEXT, METADATA as RETRIEVAL_METADATA

DESCRIPTIVE = ('summary','projectSummary','projectDescription','problemStatement','projectShortDescription','problemBeingSolved','methods','scope','objectives','potentialForNewLearning','usageOfLearningExplanation','projectBenefits1','benefits','benefitsPart1','benefitsPart2','impactAndBenefits','impactsAndBenefitsDescription','whyIsTheProjectInnovative','innovationJustification','demonstrateNoUnnecessaryDuplication','justifyWhyYouAreUndertakingAProjectSimilar','theBigIdea','solutionStatement','energySystemTransition','potentialToBenefitConsumerInVulnerableSituation','keyOutputsAndDissemination','consumerVulnerabilityImpactAssessment','successCriteria')
METADATA=('projectTitle','projectReferenceNumber','ownerNetwork','projectStatus','projectStartDate','projectEndDate','projectBudget','projectPhaseCost','technologyAreas','strategyTheme','researchAreas','precedingProjects','addPrecedingProjects','associatedInnovationProjects','thirdPartyCollaborators','fundingMechanism','techReadinessAtStart','techReadinessAtEnd')
DESCRIPTIVE = tuple(dict.fromkeys((*DESCRIPTIVE, *PRIMARY, *CONTEXT)))
METADATA = tuple(dict.fromkeys((*METADATA, *RETRIEVAL_METADATA, 'indicativeTotalNIAProjectExpenditure')))

def apparent_test(title):
    return bool(re.match(r'^(?:test project|test record|dummy|delete me)(?:\b|_)',title,re.I) or re.fullmatch(r'test',title,re.I))

def request(path,payload=None):
    if not path.startswith('/'): raise ValueError('ENA relative endpoint required')
    req=urllib.request.Request(ORIGIN+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json','User-Agent':'SPEN-Public-Evidence-Prototype/1.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req,timeout=60) as response: return response.read()
        except urllib.error.HTTPError as e:
            if e.code not in (429,502,503,504) or attempt==2: raise
            delay=e.headers.get('Retry-After','')
            time.sleep(min(60,int(delay)) if delay.isdigit() else 2**attempt)

def parse_catalogue(text):
    m=re.search(r'\bprojectsSearchResults\s*=\s*',text)
    if not m: raise ValueError('Catalogue assignment missing; schema drift')
    try: obj,_=json.JSONDecoder().raw_decode(text[m.end():].lstrip())
    except ValueError as e: raise ValueError('Catalogue JSON invalid') from e
    if not isinstance(obj,dict) or not isinstance(obj.get('Results'),list) or obj.get('Count')!=len(obj['Results']): raise ValueError('Catalogue completeness/schema mismatch')
    ids=[]
    for r in obj['Results']:
        if not all(k in r for k in ('Key','Name','OwnerNetwork','ProjectReferenceNumber','Url')): raise ValueError('Catalogue project schema changed')
        ids.append(r['Key'])
    if len(ids)!=len(set(ids)): raise ValueError('Duplicate catalogue identities')
    return obj

def catalogue(): return parse_catalogue(request('/search-results/').decode('utf-8'))

def reconcile(rows,exported,field_map,owners=OWNERS):
    if not isinstance(exported,list): raise ValueError('Expected JSON export array')
    ref_label=field_map['projectReferenceNumber']; title_label=field_map['projectTitle']
    lookup={}
    for row in rows: lookup.setdefault(str(row['ProjectReferenceNumber']).strip().lower(),[]).append(row)
    records=[]; matched=set()
    for item in exported:
        ref=clean(item.get(ref_label)); candidates=lookup.get(ref.lower(),[])
        if len(candidates)!=1: raise ValueError(f'Ambiguous or unexpected exported reference: {ref}')
        row=candidates[0]
        if clean(item.get(title_label)).lower()!=clean(row['Name']).lower(): raise ValueError(f'Export title mismatch for {ref}')
        if row['Key'] in matched: raise ValueError('Duplicate exported project')
        matched.add(row['Key']); records.append(normalise(row,item,field_map,owners=owners))
    if matched!=set(r['Key'] for r in rows): raise ValueError('Missing exported project; keeping last good snapshot')
    return records

def normalise(row,item,mapping,owners=OWNERS):
    owner=row['OwnerNetwork']
    if owners is not None and owner not in owners: raise ValueError('Out-of-scope owner')
    title=clean(row['Name']); url,fallback=link(row.get('Url'),title)
    fields={k:clean(item.get(mapping.get(k,k))) for k in DESCRIPTIVE}
    fields={k:v for k,v in fields.items() if v}
    flags=[]
    if not fields: flags.append('No descriptive fields available')
    if not clean(row['ProjectReferenceNumber']): flags.append('Project reference missing; GUID identity retained')
    if apparent_test(title): flags.append('Apparent test record')
    budget_raw=item.get(mapping.get('projectBudget')) or item.get(mapping.get('projectPhaseCost'))
    try: budget=float(re.sub(r'[^0-9.]','',str(budget_raw))) if budget_raw is not None else None
    except ValueError: budget=None
    return {'id':row['Key'],'cms_id':row.get('Id'),'reference':str(row['ProjectReferenceNumber']),'title':title,'owner':owner,'status':row.get('Status') or 'Unknown','start_date':row.get('StartDate'),'end_date':row.get('EndDate'),'form':row.get('FormType'),'themes':row.get('StrategyThemes') or [],'technology':row.get('TechnologyAreas') or [],'research':row.get('ResearchAreas') or [],'funding':row.get('FundingMechanisms') or [],'url':url,'url_is_search':fallback,'budget':budget,'budget_raw':budget_raw,'fields':fields,'raw_fields':item,'flags':flags,'detail_last_checked_at':now(),'source_checked_at':now(),'imported_at':None,'provenance':'ENA public catalogue and rich export'}

def export_rows(rows,mapping):
    fields={k:mapping[k] for k in (*METADATA,*DESCRIPTIVE) if k in mapping}
    raw=request('/umbraco/api/ExportSearchResultsToCsvApi/ExportToCsv',{'projectIds':[r['Key'] for r in rows],'fieldsToExport':fields})
    return json.loads(raw),raw

def refresh(store,progress=lambda *args:None,selected=None):
    DATA.mkdir(exist_ok=True); lock=DATA/'refresh.lock'
    try: f=lock.open('x')
    except FileExistsError: raise ValueError('Refresh already running. Remove data/refresh.lock only after verifying no refresh process remains.')
    try:
        cat=catalogue(); store.meta('catalogue_last_checked_at',now());store.meta('catalogue_count',cat['Count'])
        rows=[r for r in cat['Results'] if r['OwnerNetwork'] in OWNERS and (selected is None or r['Key'] in selected)]
        if selected is not None and len(rows)!=len(set(selected)): raise ValueError('Selected project absent from latest catalogue')
        mapping=json.loads(request('/umbraco/api/ExportSearchResultsToCsvApi/GetProperties'))
        if not all(k in mapping for k in ('projectTitle','projectReferenceNumber','ownerNetwork')): raise ValueError('Export property schema drift')
        records=[]; snapshot=DATA/'raw'/now().replace(':','-');snapshot.mkdir(parents=True)
        (snapshot/'catalogue.json').write_text(json.dumps(cat)); (snapshot/'fields.json').write_text(json.dumps(mapping))
        for start in range(0,len(rows),20):
            batch=rows[start:start+20]; exported,raw=export_rows(batch,mapping)
            (snapshot/f'export-{start}.json').write_bytes(raw)
            refs=[str(r['ProjectReferenceNumber']).strip().lower() for r in batch]
            if len(refs)!=len(set(refs)):
                # Export does not return GUIDs. A single-GUID request provides authoritative identity
                # when legacy catalogue references are shared; never disambiguate by title alone.
                for row in batch:
                    if refs.count(str(row['ProjectReferenceNumber']).strip().lower())>1:
                        single,single_raw=export_rows([row],mapping)
                        (snapshot/f"export-single-{row['Key']}.json").write_bytes(single_raw)
                        records.extend(reconcile([row],single,mapping));time.sleep(1)
                    else:
                        match=[e for e in exported if clean(e.get(mapping['projectReferenceNumber'])).lower()==str(row['ProjectReferenceNumber']).strip().lower()]
                        records.extend(reconcile([row],match,mapping))
            else: records.extend(reconcile(batch,exported,mapping))
            progress(min(start+20,len(rows)),len(rows))
            if start+20<len(rows): time.sleep(1)
        store.upsert(records,complete=selected is None)
        if selected is None: store.meta('last_successful_full_refresh_at',now())
        store.meta('refresh_error',''); return {'records':len(records),'catalogue_count':cat['Count']}
    except Exception as e:
        store.meta('refresh_error',str(e)); raise
    finally: f.close();lock.unlink(missing_ok=True)

def import_records(content,format,mapping=None):
    mapping=mapping or {}; mapping={k:v for k,v in mapping.items() if v}
    if format=='csv': rows=list(csv.DictReader(io.StringIO(content.lstrip('\ufeff'))))
    elif format=='json':
        rows=json.loads(content.lstrip('\ufeff')); rows=rows.get('projects',[]) if isinstance(rows,dict) else rows
    else: raise ValueError('Use csv or json')
    if not isinstance(rows,list) or len(rows)>5000: raise ValueError('Expected at most 5000 records')
    records=[]; errors=[]; ids=set()
    for n,raw in enumerate(rows):
        try:
            get=lambda key,default=None:raw.get(mapping.get(key,key),default)
            id=str(get('id','')).strip(); title=clean(get('title')); reference=clean(get('reference'));owner=clean(get('owner'))
            if not id or not title or not reference or owner not in OWNERS: raise ValueError('id, title, reference and exact in-scope owner required')
            if id in ids: raise ValueError('Duplicate id')
            ids.add(id)
            fields=get('fields') or {'summary':get('summary')}
            if not isinstance(fields,dict): raise ValueError('fields must be an object')
            fields={k:clean(v) for k,v in fields.items() if k in DESCRIPTIVE and clean(v)}
            url,fallback=link(get('url'),title)
            records.append({'id':id,'title':title,'reference':reference,'owner':owner,'status':clean(get('status','Unknown')),'start_date':get('start_date'),'end_date':get('end_date'),'themes':[],'technology':[],'url':url,'url_is_search':fallback,'fields':fields,'raw_fields':raw,'flags':[] if fields else ['No descriptive fields available'],'detail_last_checked_at':None,'source_checked_at':None,'imported_at':now(),'provenance':'Manual import; source-check time unknown','budget':None,'budget_raw':None})
        except (ValueError,TypeError,AttributeError) as e: errors.append({'row':n+1,'error':str(e)})
    return records,errors
