"""Source-only public metadata for the portfolio map. No generative inference."""
import ast
import math
import re
from collections import defaultdict
from datetime import date, datetime

from core.text import clean

FINANCES = {
    'budget': ('Project budget', 'projectBudget', 'Project Budget'),
    'cost': ('Total project costs', 'projectPhaseCost', 'Total Project Costs'),
    'nia': ('Indicative NIA expenditure', 'indicativeTotalNIAProjectExpenditure', 'Indicative Total NIA Project Expenditure'),
}
UNKNOWN = 'Not recorded'


def raw_value(project, key, label):
    raw = project.get('raw_fields') or {}
    return raw.get(label, raw.get(key))


def values(value):
    if isinstance(value, (tuple, list)):
        return sorted({clean(v) for v in value if clean(v)}, key=str.casefold)
    text = clean(value)
    if not text or text.casefold() in ('none', 'n/a', '[]', 'null'):
        return []
    if text.startswith('['):
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, list):
                return values(parsed)
        except (ValueError, SyntaxError):
            pass
    # ENA taxonomy exports use comma/semicolon separators; narrative fields never use this parser.
    return sorted({v.strip() for v in re.split(r'[,;\n]', text) if v.strip()}, key=str.casefold)


def iso_date(value):
    if not value:
        return None
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        try:
            return datetime.strptime(text, '%d/%m/%Y').date().isoformat()
        except ValueError:
            return None


def amount(value):
    """Parse one unambiguous GBP scalar. Never concatenate multiple narrative amounts."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else None
    text = clean(value)
    match = re.fullmatch(r'(?:GBP\s*|£\s*)?(\d+(?:,\d{3})*(?:\.\d+)?)\s*(k|m|million|thousand)?', text, re.I)
    if not match:
        return None
    factor = {'k': 1000, 'thousand': 1000, 'm': 1000000, 'million': 1000000}.get((match[2] or '').lower(), 1)
    result = float(match[1].replace(',', '')) * factor
    return result if math.isfinite(result) else None


def reference_key(value):
    # Keep punctuation significant: NIA_A-1 must not silently collide with NIA_A1.
    return re.sub(r'\s+', '', str(value)).casefold()


def project_metadata(project):
    def source(key, label, fallback=None):
        value = raw_value(project, key, label)
        return fallback if value is None else value

    money = {}
    for mode, (label, key, field) in FINANCES.items():
        raw = source(key, field, project.get('budget_raw') if mode == 'budget' else None)
        money[mode] = {'label': label, 'value': amount(raw), 'raw': clean(raw), 'field': key,
                       'checked_at': project.get('financial_checked_at') or project.get('source_checked_at')}
    preceding = []
    for key, label in [('precedingProjects', 'Preceding Projects'), ('addPrecedingProjects', 'Add Preceding Project(s)')]:
        for ref in values(raw_value(project, key, label)):
            if ref not in [p['reference'] for p in preceding]:
                preceding.append({'reference': ref, 'field': key})
    start = iso_date(source('projectStartDate', 'Project Start Date', project.get('start_date')))
    end = iso_date(source('projectEndDate', 'Project End Date', project.get('end_date')))
    invalid_dates = bool(start and end and start > end)
    narrative = project.get('fields') or {}
    excerpt = next((narrative[k] for k in ('summary', 'projectSummary', 'projectDescription', 'projectShortDescription') if narrative.get(k)), next(iter(narrative.values()), ''))
    return {'id': project['id'], 'title': project['title'], 'reference': project.get('reference', ''),
            'owner': project.get('owner') or UNKNOWN,
            'participants': values(source('collaboratingNetworks', 'Collaborating Networks')),
            'sector': values(source('leadSector', 'Lead Sector')),
            'status': clean(source('projectStatus', 'Project Status', project.get('status'))) or UNKNOWN,
            'funding': values(project.get('funding')) or values(source('fundingMechanism', 'Funding Mechanism')),
            'technology': values(project.get('technology')) or values(source('technologyAreas', 'Technology Areas')),
            'themes': values(project.get('themes')) or values(source('strategyTheme', 'Strategy Theme')),
            'research': values(project.get('research')) or values(source('researchAreas', 'Research Areas')),
            'start_date': start, 'end_date': end, 'invalid_dates': invalid_dates,
            'money': money, 'preceding': preceding, 'url': project.get('url'),
            'excerpt': excerpt[:700], 'checked_at': project.get('source_checked_at'),
            'flags': project.get('flags', []), 'semantic_hash': project.get('semantic_hash'),
            'field_sources': {'participants': 'collaboratingNetworks', 'sector': 'leadSector', 'owner': 'ownerNetwork', 'status': 'projectStatus', 'funding': 'fundingMechanism',
                             'technology': 'technologyAreas', 'themes': 'strategyTheme', 'research': 'researchAreas',
                             'start_date': 'projectStartDate', 'end_date': 'projectEndDate'}}


def resolve_lineage(nodes):
    refs = defaultdict(list)
    for node in nodes:
        if node['reference']:
            refs[reference_key(node['reference'])].append(node['id'])
    edges = []
    for node in nodes:
        for item in node['preceding']:
            candidates = refs[reference_key(item['reference'])]
            state = 'resolved' if len(candidates) == 1 else 'ambiguous' if candidates else 'outside'
            item.update({'state': state, 'id': candidates[0] if len(candidates) == 1 else None})
            if item['id'] == node['id']:
                item['state'] = 'self-link'
            if item['state'] == 'resolved':
                edge = {'source': item['id'], 'target': node['id'], 'reference': item['reference'], 'field': item['field']}
                if edge not in edges:
                    edges.append(edge)
    return edges
