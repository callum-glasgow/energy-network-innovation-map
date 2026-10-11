import hashlib
import html
import re
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlencode
from core.config import ORIGIN

class Cleaner(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts = []; self.hidden = 0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.hidden += 1
        if tag in ('p','br','li','div'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.hidden = max(0,self.hidden-1)
        if tag in ('p','li','div'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.hidden: self.parts.append(data)

def clean(value):
    if value is None: return ''
    if isinstance(value, (list,dict)): return clean(str(value))
    parser = Cleaner(); parser.feed(str(value))
    return re.sub(r'\s+', ' ', html.unescape(''.join(parser.parts))).strip()

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def tokens(text):
    return re.findall(r'[a-z0-9]+', text.lower())

def link(url, title):
    resolved = urljoin(ORIGIN, url or '')
    parsed = urlparse(resolved)
    if url and parsed.scheme == 'https' and parsed.netloc == urlparse(ORIGIN).netloc and not parsed.username:
        return resolved, False
    return ORIGIN + '/search-results/?' + urlencode({'search':title}), True

def passages(project_id, fields):
    result = []
    for field, text in sorted(fields.items()):
        # Nonoverlapping, stable source chunks keep citations and project votes distinct.
        sentences = re.split(r'(?<=[.!?])\s+', text)
        chunks=[]; chunk=''
        for sentence in sentences:
            for start in range(0,len(sentence),2400):
                piece=sentence[start:start+2400]
                if len(chunk)+len(piece)>2800 and chunk: chunks.append(chunk); chunk=''
                chunk=(chunk+' '+piece).strip()
        if chunk: chunks.append(chunk)
        for i,part in enumerate(chunks):
            h=digest(part)
            result.append({'id':f'{project_id}:{field}:{i}:{h[:12]}','project_id':project_id,'field':field,'text':part,'hash':h})
    return result
