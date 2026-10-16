from contextlib import closing
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

sys.path.insert(0,'/mnt/quant/strategies/stocks-quant')
from workflows import blog_delivery as delivery, daily_blog as blog

DAY=date(2026,10,16)
SETTINGS={'enabled':True,'upstream_task_id':'evidence','min_complete_sources':2,
          'min_unused_sources':1,'min_body_chars':1000,'max_source_age_days':14,'recent_publication_days':7}

def packet():
    return {'day':DAY.isoformat(),'sources':[{'id':str(i),'url':f'https://example.org/{i}',
            'source_date':'2026-10-15','evidence_level':'cached_webpage'} for i in range(2)],
            'evidence':[{'source_ids':[str(i)],'record_type':'webpage','text':'e'*1100} for i in range(2)]}

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.db=self.root/'news.sqlite3';self.site=self.root/'site';self.site.mkdir()
        self.config={'timezone':'Asia/Shanghai','workflow':{'readiness':SETTINGS,
                    'website_state':str(self.site),'website_repo':'/mnt/quant/strategies/stocks-quant'}}
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('CREATE TABLE tasks(id TEXT,enabled INTEGER)')
            db.execute('INSERT INTO tasks VALUES (?,1)',('evidence',))
            db.execute('CREATE TABLE task_runs(id TEXT,task_id TEXT,status TEXT,started_at TEXT,finished_at TEXT,metadata_json TEXT,created_at TEXT)')

    def add_run(self,status='succeeded',success=True,stamp='2026-10-15T23:00:00+00:00'):
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('INSERT INTO task_runs VALUES (?,?,?,?,?,?,?)',
                       ('run','evidence',status,stamp,stamp if status!='running' else None,
                        json.dumps({'result':{'success':success}}),stamp))

    def test_complete_unused_pages_are_required_not_headlines(self):
        data=packet()
        self.assertTrue(delivery.assess_packet(data,[],SETTINGS,DAY)['ready'])
        for mutation in ('headline','short','stale','future','unknown_date'):
            modified=deepcopy(data)
            if mutation=='headline': modified['evidence'][0]['record_type']='feed_entry'
            if mutation=='short': modified['evidence'][0]['text']='headline'
            if mutation=='stale': modified['sources'][0]['source_date']='2026-09-01'
            if mutation=='future': modified['sources'][0]['source_date']='2026-10-17'
            if mutation=='unknown_date': modified['sources'][0]['source_date']=None
            self.assertFalse(delivery.assess_packet(modified,[],SETTINGS,DAY)['ready'],mutation)
        recent=[{'published_at':'2026-10-15','sources':data['sources']}]
        self.assertFalse(delivery.assess_packet(data,recent,SETTINGS,DAY)['ready'])
        recent[0]['published_at']='2026-09-01'
        self.assertTrue(delivery.assess_packet(data,recent,SETTINGS,DAY)['ready'])

    def test_duplicate_urls_cannot_fill_source_requirement(self):
        data=packet();data['sources'][1]['url']=data['sources'][0]['url']
        self.assertFalse(delivery.assess_packet(data,[],SETTINGS,DAY)['ready'])

    def test_upstream_uses_beijing_day_and_business_success(self):
        self.add_run()
        self.assertTrue(delivery.upstream_state(self.db,'evidence',DAY,ZoneInfo('Asia/Shanghai'))['ready'])
        self.assertFalse(delivery.upstream_state(self.db,'evidence',date(2026,10,17),ZoneInfo('Asia/Shanghai'))['ready'])
        with closing(sqlite3.connect(self.db)) as db,db:
            db.execute('UPDATE task_runs SET metadata_json=?',(json.dumps({'result':{'success':False}}),))
        self.assertFalse(delivery.upstream_state(self.db,'evidence',DAY,ZoneInfo('Asia/Shanghai'))['ready'])

    def test_blocked_gate_never_reserves_day_or_calls_model_and_can_later_be_ready(self):
        runner=Mock(side_effect=AssertionError('must not call model'))
        with patch.object(blog,'collect_packet',return_value=packet()):
            result=blog.run(self.config,self.root,self.db,self.root/'first',execute=True,model_runner=runner,day=DAY)
        self.assertEqual(result['business_status'],'preflight_blocked')
        runner.assert_not_called()
        self.assertFalse((self.root/'data/runs/daily-blog-days'/f'{DAY}.json').exists())
        self.add_run()
        self.assertTrue(delivery.preflight(self.config,self.root,self.db,DAY,packet=packet())['success'])

    def test_active_or_disabled_upstream_does_not_pass(self):
        self.add_run(status='running')
        self.assertFalse(delivery.preflight(self.config,self.root,self.db,DAY,packet=packet())['success'])
        with closing(sqlite3.connect(self.db)) as db,db: db.execute('UPDATE tasks SET enabled=0')
        self.assertEqual(delivery.upstream_state(self.db,'evidence',DAY,ZoneInfo('Asia/Shanghai'))['reason'],'upstream_disabled_or_missing')

    def test_delivery_marker_alone_never_counts_as_publication(self):
        marker=self.root/'data/runs/daily-blog-days'/f'{DAY}.json'
        marker.parent.mkdir(parents=True);marker.write_text(json.dumps({'status':'published','run_id':'prior'}))
        with patch.object(blog,'collect_packet',return_value=packet()):
            result=delivery.inspect_delivery(self.config,self.root,self.db,DAY)
        self.assertFalse(result['success'])
        self.assertEqual(result['business_status'],'daily_publication_missing')
        self.assertTrue(result['needs_attention'])
        self.assertEqual(result['attempt']['run_id'],'prior')

    def test_validated_publication_skips_all_collection_and_model_work(self):
        with patch('web.blog_runtime.load_runtime_articles',return_value=[{'published_at':str(DAY),'slug':'article'}]),patch.object(blog,'collect_packet',side_effect=AssertionError('no fetch')):
            result=delivery.inspect_delivery(self.config,self.root,self.db,DAY)
            self.assertEqual(result['business_status'],'publication_verified')
            self.assertEqual(delivery.preflight(self.config,self.root,self.db,DAY)['business_status'],'already_published')

    def test_rendered_failure_is_not_reported_as_successful_delivery(self):
        self.config['workflow']['delivery_surfaces']={'enabled':True}
        with patch('web.blog_runtime.load_runtime_articles',return_value=[{'published_at':str(DAY),'slug':'article'}]), patch('workflows.publication_surfaces.inspect_surfaces',return_value={'success':False,'local_http_requests':4,'issues':['en:/blog:article_cards_missing']}):
            result=delivery.inspect_delivery(self.config,self.root,self.db,DAY)
        self.assertFalse(result['success'])
        self.assertTrue(result['needs_attention'])
        self.assertEqual(result['business_status'],'publication_surface_mismatch')

if __name__=='__main__':
    unittest.main()
