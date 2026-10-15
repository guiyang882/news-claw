from contextlib import closing
from datetime import datetime, timezone
import hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from collectors.blog_evidence import permitted,select_sources

class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.db=self.root/'db'
        self.now=datetime(2026,10,15,6,tzinfo=timezone.utc)
        self.task={'collector':{'discovery':{'lookback_days':7,'max_pages_per_run':6,'max_pages_per_host':2,
            'official_url_prefixes':['https://blogs.nvidia.com/blog/'],
            'official_feed_hosts':['blogs.nvidia.com'],'title_pattern':'AI'}}}
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE documents (id TEXT,canonical_url TEXT,title TEXT,published_at TEXT,fetched_at TEXT,normalized_path TEXT,content_hash TEXT,source_json TEXT,language TEXT)')
    def add(self,url,kind='feed_entry',stamp='2026-10-14T06:00:00+00:00',source='https://blogs.nvidia.com/feed/'):
        record={'canonical_url':url,'record_type':kind,'text':'Article text '*200}
        raw=json.dumps(record,ensure_ascii=False,sort_keys=True).encode();digest=hashlib.sha256(raw).hexdigest()
        path=self.root/'data/normalized'/f'{digest}.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)',(digest,url,'AI announcement',stamp,stamp,str(path.relative_to(self.root)),digest,json.dumps({'type':'rss' if kind=='feed_entry' else 'page','url':source,'name':'Official'}),'en'))
        return path
    def test_url_boundary(self):
        prefixes=self.task['collector']['discovery']['official_url_prefixes']
        self.assertTrue(permitted('https://blogs.nvidia.com/blog/a/',prefixes))
        for url in ['https://blogs.nvidia.com.evil/blog/a/','https://user@blogs.nvidia.com/blog/a/','http://blogs.nvidia.com/blog/a/','https://blogs.nvidia.com/blog/a/?url=x']:
            self.assertFalse(permitted(url,prefixes))
    def test_cache_first_and_provenance(self):
        self.add('https://blogs.nvidia.com/blog/cached/')
        self.add('https://blogs.nvidia.com/blog/cached/','webpage')
        self.add('https://blogs.nvidia.com/blog/new/')
        self.add('https://blogs.nvidia.com/blog/bad/',source='https://untrusted.example/feed')
        self.add('https://blogs.nvidia.com/blog/future/',stamp='2026-10-16T00:00:00+00:00')
        result=select_sources(self.task,self.root,self.db,self.now)
        self.assertEqual([r['url'] for r in result],['https://blogs.nvidia.com/blog/new/'])
        self.assertEqual(result[0]['published_at'],'2026-10-14T06:00:00+00:00')
        self.assertTrue(result[0]['obey_robots_txt'])
    def test_per_host_bound_and_corrupt_cache(self):
        for i in range(5):self.add(f'https://blogs.nvidia.com/blog/{i}/')
        self.assertEqual(len(select_sources(self.task,self.root,self.db,self.now)),2)
        path=self.add('https://blogs.nvidia.com/blog/tamper/')
        path.write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash mismatch'):
            select_sources(self.task,self.root,self.db,self.now)

class PageBodyTest(unittest.TestCase):
    def test_page_preserves_discovery_date_and_rejects_thin_body(self):
        from scrapy.http import HtmlResponse, Request
        from collectors.news import NewsSpider
        from unittest.mock import patch
        source={'name':'Official','url':'https://blogs.nvidia.com/blog/test/','type':'page',
                'published_at':'2026-10-14T06:00:00+00:00','minimum_text_chars':1000}
        with tempfile.TemporaryDirectory() as td:
            task={'collector':{'sources':[source]},'options':{}}
            spider=NewsSpider(task,Path(td))
            def response(body):
                return HtmlResponse(source['url'],body=body.encode(),encoding='utf-8',
                                    request=Request(source['url'],meta={'source':source}))
            with patch.object(spider,'archive',return_value={}):
                items=list(spider.parse_source(response('<title>Official</title><body>'+('evidence '*150)+'</body>')))
                self.assertEqual(items[0]['published_at'],source['published_at'])
                self.assertEqual(items[0]['record_type'],'webpage')
                self.assertEqual(list(spider.parse_source(response('<body>brief</body>'))),[])
                self.assertTrue(spider.errors)
