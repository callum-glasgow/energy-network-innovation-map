import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'
RETRIEVAL_PROFILE = os.getenv('SMART_EMA_RETRIEVAL_PROFILE', 'large-v3')
if RETRIEVAL_PROFILE not in ('legacy', 'large-v2', 'large-v3'):
    raise ValueError('SMART_EMA_RETRIEVAL_PROFILE must be legacy, large-v2 or large-v3')
# Separate recipes preserve the legacy and historical v2 indexes for rollback.
DB = DATA / ({'legacy':'projects.sqlite3', 'large-v2':'projects-large-v2.sqlite3', 'large-v3':'projects-large-v3.sqlite3'}[RETRIEVAL_PROFILE])
LEDGER = DATA / 'spend.sqlite3'
OUTPUTS = ROOT / 'outputs'
OWNERS = ('SP Energy Networks Distribution', 'SP Energy Networks Transmission')
ORIGIN = 'https://smarter.energynetworks.org'
SCOPE = 'SP Energy Networks owned Distribution and Transmission projects only. Other networks and participant-only projects are excluded. PDFs were not searched.'
LUNA = 'gpt-6-luna'
EMBEDDING = 'text-embedding-3-small' if RETRIEVAL_PROFILE == 'legacy' else 'text-embedding-3-large'
DIMENSIONS = 512 if RETRIEVAL_PROFILE == 'legacy' else 1024
RECIPE = {'legacy':'luna-summary-v1', 'large-v2':'luna-search-large-v2', 'large-v3':'luna-search-profile-v3'}[RETRIEVAL_PROFILE]

def budget_cap():
    value = float(os.getenv('SMART_EMA_BUDGET_USD', '5'))
    if not 0 <= value <= 5:
        raise ValueError('SMART_EMA_BUDGET_USD must be between 0 and 5')
    return value
