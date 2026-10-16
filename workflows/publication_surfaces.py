"""Read rendered publication surfaces on loopback only; never follow redirects."""
from html.parser import HTMLParser
import json
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Surface(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack=[]
        self.cards=set()
        self.navigation=set()
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        classes=attrs.get('class','').split()
        if tag=='a':
            href=attrs.get('href','')
            if any('article-card' in item[1] for item in self.stack):
                self.cards.add(href)
            if any('site-nav' in item[1] for item in self.stack):
                self.navigation.add(href)
        if tag not in {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}:
            self.stack.append((tag,classes))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                del self.stack[i:]
                break


def _fetch(path, origin):
    request=Request(origin+path,headers={'User-Agent':'news-claw-publication-audit/1.0'})
    with build_opener(NoRedirect).open(request,timeout=8) as response:
        raw=response.read(8_000_001)
        if len(raw)>8_000_000:
            raise ValueError('publication surface exceeds response budget')
        return raw.decode('utf-8')


def inspect_surfaces(slugs, settings, fetch=None):
    origin=settings.get('origin','http://127.0.0.1:3000')
    if origin!='http://127.0.0.1:3000':
        raise ValueError('publication audit permits only the local frontend')
    fetch=fetch or (lambda path: _fetch(path,origin))
    issues=[]
    requests=0
    def read(path):
        nonlocal requests
        requests+=1
        return fetch(path)
    try:
        items=json.loads(read('/api/v1/articles?page_size=50'))['data']['items']
        expected={item['slug'] for item in items}
        if not set(slugs).issubset(expected):
            issues.append('published_article_missing_from_api')
        # Home uses the same ordered catalogue, not a separate hard-coded list.
        featured={item['slug'] for item in items[:3]}
        for language in ('zh-CN','en'):
            suffix='?lang=en' if language=='en' else ''
            for path in ('/','/blog','/about','/editorial'):
                surface=Surface(read(path+suffix))
                nav={urlsplit(href).path for href in surface.navigation}
                if not {'/blog','/radar','/developers'}.issubset(nav):
                    issues.append(f'{language}:{path}:navigation_incomplete')
                if path in ('/','/blog'):
                    cards={urlsplit(href).path.removeprefix('/blog/') for href in surface.cards
                           if (parse_qs(urlsplit(href).query).get('lang',['zh-CN'])[0]=='en')==(language=='en')}
                    required=featured if path=='/' else expected
                    if not required.issubset(cards):
                        issues.append(f'{language}:{path}:article_cards_missing')
            for slug in slugs:
                # Slugs originate in validated runtime records, not raw task parameters.
                if not slug or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in slug):
                    raise ValueError('invalid published slug')
                html=read('/blog/'+slug+suffix)
                if '<h1' not in html or ('lang="en"' not in html if language=='en' else 'lang="zh-CN"' not in html):
                    issues.append(f'{language}:{slug}:article_unavailable')
    except Exception as error:
        issues.append(type(error).__name__+': '+str(error)[:200])
    return {'success':not issues,'issues':issues,'local_http_requests':requests,
            'external_requests':0,'model_calls':0}
