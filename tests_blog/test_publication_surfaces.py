import json
import unittest
from workflows.publication_surfaces import inspect_surfaces


def fixture(path):
    if path.startswith('/api/'):
        return json.dumps({'data':{'items':[{'slug':'latest'},{'slug':'older'}]}})
    en='lang=en' in path
    suffix='?lang=en' if en else ''
    nav='<nav class="site-nav">'+''.join(f'<a href="{p}{suffix}">Link</a>' for p in ('/blog','/radar','/developers'))+'</nav>'
    cards=''.join(f'<article class="article-card"><a href="/blog/{slug}{suffix}">Title</a></article>' for slug in ('latest','older'))
    return f'<html lang="{"en" if en else "zh-CN"}"><body>{nav}<h1>Research</h1>{cards}</body></html>'


class PublicationSurfacesTests(unittest.TestCase):
    def test_both_languages_and_all_surfaces(self):
        seen=[]
        def fetch(path):
            seen.append(path);return fixture(path)
        result=inspect_surfaces(['latest'],{},fetch)
        self.assertTrue(result['success'],result)
        self.assertEqual(result['local_http_requests'],11)
        self.assertIn('/blog/latest?lang=en',seen)
        self.assertEqual(result['external_requests'],0)

    def test_stale_english_list_is_detected_even_if_slug_exists_in_script(self):
        def fetch(path):
            text=fixture(path)
            if path=='/blog?lang=en':
                text=text.replace('<article class="article-card"><a href="/blog/latest?lang=en">Title</a></article>','<script>"/blog/latest?lang=en"</script>')
            return text
        result=inspect_surfaces(['latest'],{},fetch)
        self.assertIn('en:/blog:article_cards_missing',result['issues'])

    def test_stale_home_and_navigation_detected(self):
        def fetch(path):
            text=fixture(path)
            if path=='/':text=text.replace('class="article-card"','class="other"')
            if path=='/about':text=text.replace('href="/developers"','href="/old"')
            return text
        result=inspect_surfaces(['latest'],{},fetch)
        self.assertIn('zh-CN:/:article_cards_missing',result['issues'])
        self.assertIn('zh-CN:/about:navigation_incomplete',result['issues'])

    def test_api_missing_article_or_server_failure_cannot_pass(self):
        self.assertFalse(inspect_surfaces(['missing'],{},fixture)['success'])
        def fail(path):raise TimeoutError('local frontend timeout')
        self.assertFalse(inspect_surfaces(['latest'],{},fail)['success'])

    def test_remote_target_is_rejected_before_network(self):
        with self.assertRaises(ValueError):
            inspect_surfaces(['latest'],{'origin':'https://example.com'},lambda _:self.fail('network'))

    def test_paginated_library_is_checked_in_both_languages(self):
        seen=[]
        def fetch(path):
            seen.append(path)
            text=fixture(path)
            suffix='?lang=en' if 'lang=en' in path else ''
            if path in ('/blog','/blog?lang=en'):
                text=text.replace(f'<article class="article-card"><a href="/blog/older{suffix}">Title</a></article>','')
                next_url='/blog?lang=en&amp;page=2' if suffix else '/blog?page=2'
                text+=f'<nav class="library-pagination"><a rel="next" href="{next_url}">Next</a></nav>'
            return text
        self.assertTrue(inspect_surfaces(['latest'],{},fetch)['success'])
        self.assertIn('/blog?page=2',seen)
        self.assertIn('/blog?lang=en&page=2',seen)

    def test_external_pagination_is_rejected_without_fetching(self):
        seen=[]
        def fetch(path):
            seen.append(path)
            text=fixture(path)
            if path=='/blog':
                text+='<nav class="library-pagination"><a rel="next" href="https://example.com/blog?page=2">Next</a></nav>'
            return text
        self.assertFalse(inspect_surfaces(['latest'],{},fetch)['success'])
        self.assertFalse(any(path.startswith('https:') for path in seen))

if __name__=='__main__':unittest.main()
