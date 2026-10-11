"""Local query preparation and cached original-source keyword evidence.

Spelling suggestions never rewrite source text or identifiers. Phrase aliases
are curated concepts, rather than an unrestricted bag of synonymous words.
"""
import math
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files

from symspellpy import SymSpell, Verbosity

from core.text import tokens

STOP = set('a an the and or for to of in on with how can could would we our is are find project projects using use from by at as into during through their its that these those this it be was were been being will should about between also'.split())
ALIASES = (
    ('lvdc', 'low voltage direct current', 'low voltage dc'),
    ('hvdc', 'high voltage direct current', 'high voltage dc'),
    ('mvdc', 'medium voltage direct current', 'medium voltage dc'),
    ('lv', 'low voltage'), ('hv', 'high voltage'),
    ('ohl', 'overhead line', 'overhead lines', 'overheadline', 'overheadlines'),
    ('ev', 'electric vehicle', 'electric vehicles'),
    ('der', 'distributed energy resource', 'distributed energy resources'),
    ('v2g', 'vehicle to grid'),
    ('psr', 'priority services register'),
    ('modelling', 'modeling'), ('optimisation', 'optimization'),
    ('decarbonisation', 'decarbonization'), ('sulphur', 'sulfur'),
    ('cybersecurity', 'cyber security'),
)
SYNONYMS = {
    'vegetation': ('tree', 'trees', 'encroachment'),
    'tree': ('trees', 'vegetation'), 'trees': ('tree', 'vegetation', 'canopy'),
    'flexibility': ('demand response',),
    'vulnerable': ('vulnerability',),
    'weather': ('storm', 'forecasting'),
}
PROTECTED = {v for group in ALIASES for v in group if len(v) <= 5}
ALIAS_MAP = {v: group for group in ALIASES for v in group}


@lru_cache(maxsize=1)
def english_words():
    # Recognition only: correction candidates still come from the source corpus.
    # A valid English word absent from ENA is not automatically a spelling error.
    dictionary = files('symspellpy').joinpath('frequency_dictionary_en_82_765.txt')
    return frozenset(line.split()[0] for line in dictionary.read_text(encoding='utf-8').splitlines() if line)


def normalized(text):
    return ' ' + ' '.join(tokens(text)) + ' '


def reference_key(text):
    return re.sub(r'[^a-z0-9]', '', text.lower())


def is_reference_query(text):
    # Recognize complete SPEN/legacy reference forms, not ordinary proposals
    # containing a number. Unknown IDs must not match their generic NIA prefix.
    return bool(re.fullmatch(r'(?:nia(?:spen|spt|sp)?|sif(?:spen|spt)?|ifi|nic(?:spen|spt)?)\d+[a-z0-9]*',reference_key(text)))


def excerpt_window(best,terms=()):
    if not best:
        return {'excerpt':'No descriptive evidence supplied.','matched_passage_id':None}
    text=best['text'];start=0
    matches=[m.start() for t in terms for m in re.finditer(
        r'\b'+r'[\s\W]+'.join(re.escape(w) for w in tokens(t))+r'\b',text,re.IGNORECASE)]
    if matches:
        start=max(0,min(matches)-100)
        if start:
            boundary=text.find(' ',start,start+40)
            if boundary>=0:start=boundary+1
    end=min(len(text),start+400)
    if end<len(text):
        boundary=text.rfind(' ',max(start,end-40),end)
        if boundary>start:end=boundary
    return {'excerpt':text[start:end],'matched_passage_id':best['id']}


def variants(term, vocabulary):
    """Only add conservative inflections that actually occur in the corpus."""
    result = [term]
    if term.endswith('ies'):
        candidates = [term[:-3] + 'y']
    elif term.endswith('s') and not term.endswith(('ss', 'us', 'is')):
        candidates = [term[:-1]]
    else:
        candidates = [term + 's', term[:-1] + 'ies' if term.endswith('y') else '']
    return result + [t for t in candidates if t and t in vocabulary]


@dataclass(frozen=True)
class Group:
    original: str
    primary: tuple
    secondary: tuple = ()
    corrected: bool = False


@dataclass(frozen=True)
class Plan:
    groups: tuple
    corrections: tuple
    suggestions: tuple

    @property
    def primary(self):
        return list(dict.fromkeys(t for g in self.groups for t in g.primary))[:40]

    @property
    def secondary(self):
        return [t for t in dict.fromkeys(t for g in self.groups for t in g.secondary) if t not in self.primary][:40]

    @property
    def terms(self):
        return (self.primary + self.secondary)[:40]


class KeywordIndex:
    def __init__(self, projects, passages=()):
        self.projects = projects
        self.docs = {}
        self.passages = defaultdict(list)
        counts = Counter()
        self.postings = defaultdict(list)
        self.lengths = {}
        for p in projects:
            title = tokens(p['title']); body = tokens(' '.join(p['fields'].values()))
            ref = tokens(p['reference'])
            doc_counts = Counter(title + body + ref)
            counts.update(doc_counts)
            self.docs[p['id']] = {
                'terms': frozenset(doc_counts), 'title': normalized(p['title']),
                'title_terms': frozenset(t for t in title if t not in STOP),
                'texts': tuple(normalized(v) for v in [p['title'], p['reference'], *p['fields'].values()]),
                'counts': Counter(title * 6 + ref * 10 + body),
            }
        for row in passages:
            seq = tokens(row['text']); frequency = Counter(seq)
            prepared = {**row, 'terms': frozenset(frequency), 'normalized': ' ' + ' '.join(seq) + ' '}
            self.passages[row['project_id']].append(prepared)
            self.lengths[row['id']] = len(seq)
            for word, frequency in frequency.items():
                self.postings[word].append((row['id'], row['project_id'], frequency))
        self.average_length = sum(self.lengths.values()) / max(1, len(self.lengths))
        self.vocabulary = frozenset(counts)
        self.word_counts = counts
        self._speller = None
        self._spelling_lock = threading.Lock()

    @property
    def speller(self):
        with self._spelling_lock:
            if self._speller is None:
                speller = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
                for word, frequency in self.word_counts.items():
                    if word.isalpha() and len(word) >= 4:
                        speller.create_dictionary_entry(word, frequency)
                self._speller = speller
            return self._speller

    def matches(self, id, term):
        doc = self.docs[id]
        if ' ' not in term:
            return term in doc['terms']
        phrase = ' ' + term + ' '
        return any(phrase in text for text in doc['texts'])

    def prepare(self, query, expansion=True):
        raw = re.findall(r'[a-zA-Z0-9]+', query)
        words = [t.lower() for t in raw]
        groups = []; corrections = []; suggestions = []; seen = set(); i = 0
        while i < len(words) and len(groups) < 40:
            term = words[i]; width = 1
            if expansion:
                for length in range(min(5, len(words) - i), 0, -1):
                    phrase = ' '.join(words[i:i+length])
                    if phrase in ALIAS_MAP:
                        term = phrase; width = length; break
            original_case = raw[i]; i += width
            if term in STOP or term in seen:
                continue
            seen.add(term); corrected = False; target = term
            if expansion and ' ' not in term and term not in self.vocabulary and term not in PROTECTED and term not in english_words():
                # IDs, short acronyms and negating prefixes must retain meaning.
                protected = any(c.isdigit() for c in term) or (original_case.isupper() and len(term) <= 5)
                if len(term) >= 5 and not protected:
                    distance = 1 if len(term) < 9 else 2
                    choices = self.speller.lookup(term, Verbosity.ALL, max_edit_distance=distance)
                    choices = [c for c in choices if not any(
                        term == prefix + c.term or c.term == prefix + term
                        for prefix in ('un', 'in', 'im', 'ir', 'dis', 'non'))]
                    if choices:
                        best_distance = min(c.distance for c in choices)
                        closest = [c for c in choices if c.distance == best_distance]
                        if len(closest) == 1:
                            target = closest[0].term; corrected = True
                            corrections.append({'from': term, 'to': target})
                        else:
                            suggestions.append({'from': term, 'options': [c.term for c in closest[:3]]})
            primary = ALIAS_MAP.get(target, (target,)) if expansion else (target,)
            inflections = tuple(variants(target, self.vocabulary)[1:]) if expansion and len(primary) == 1 else ()
            secondary = inflections + SYNONYMS.get(target, ()) if expansion else ()
            groups.append(Group(term, tuple(primary), tuple(secondary), corrected))
        return Plan(tuple(groups), tuple(corrections), tuple(suggestions))

    def coverage(self, id, plan):
        matched = []; quality = 0; phrases = 0
        for group in plan.groups:
            primary = next((t for t in group.primary if self.matches(id, t)), None)
            secondary = next((t for t in group.secondary if self.matches(id, t)), None)
            if primary:
                quality += .9 if group.corrected else 1
                phrases += int(' ' in primary)
                matched.append(primary)
            elif secondary:
                quality += .5; matched.append(secondary)
        return len(matched), quality, phrases, matched

    def passage_scores(self, terms, allowed):
        """BM25 over original passages; each project contributes its best passage."""
        scores = defaultdict(float); owners = {}; count = len(self.lengths)
        for term in dict.fromkeys(t for clause in terms for t in tokens(clause)):
            posting = self.postings.get(term, ())
            idf = math.log(1 + (count - len(posting) + .5) / (len(posting) + .5))
            for pid, owner, tf in posting:
                if owner in allowed:
                    scores[pid] += idf * tf * 2.2 / (tf + 1.2 * (.25 + .75 * self.lengths[pid] / max(1, self.average_length)))
                    owners[pid] = owner
        best = defaultdict(float)
        for pid, score in scores.items():
            best[owners[pid]] = max(best[owners[pid]], score)
        return best

    def excerpt(self, id, plan, exact=False):
        source = self.passages[id]
        if exact:
            best = next((p for p in source if p['field'] in ('summary', 'projectSummary')), source[0] if source else None)
        else:
            def strength(p):
                # Phrase evidence must occur together in this source passage.
                def present(term):
                    return (' ' + term + ' ') in p['normalized'] if ' ' in term else term in p['terms']
                return sum(max([1.5 if ' ' in t else 1 for t in g.primary if present(t)] +
                               [.35 for t in g.secondary if present(t)] + [0]) for g in plan.groups)
            best = max(source, key=strength, default=None)
        # The excerpt remains an exact substring of its cited original passage.
        return excerpt_window(best,() if exact else plan.terms)
