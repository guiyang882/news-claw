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

if __name__=='__main__':unittest.main()
