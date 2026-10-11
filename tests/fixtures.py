from core.config import OWNERS

def project(id='p1',reference='NIA_SPEN_0137',title='Project Canopy',summary='Vegetation and tree encroachment forecasting around overhead lines.'):
    return {'id':id,'reference':reference,'title':title,'owner':OWNERS[0],'status':'Live','start_date':'2026-06-01','end_date':None,'url':'https://smarter.energynetworks.org/projects/canopy/','url_is_search':False,'fields':{'summary':summary},'flags':[],'themes':['Resilience'],'technology':[],'source_checked_at':'2026-10-05T00:00:00Z','detail_last_checked_at':'2026-10-05T00:00:00Z','imported_at':None,'provenance':'Fixture','budget':None,'budget_raw':None}
