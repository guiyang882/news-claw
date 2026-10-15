import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from collectors.dependency_evidence import select_relationship_sources
from workflows.daily_blog import model_failure_kind, ModelRunner
from workflows.dependencies import run, digest, REPO


class ResearchSafetyTest(unittest.TestCase):
    def test_retry_waits_once_and_stays_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner=ModelRunner({'workflow':{'transient_retry':{'max_retries':1,'delay_seconds':45},'network_policy':{'max_cli_invocations_per_run':2}}},Path(tmp))
            def call(*args):
                runner.calls.append({'failure_kind':'provider_stream_interrupted'})
                if len(runner.calls)==1:raise ValueError('interrupted')
                return {'ok':True}
            with patch.object(runner,'_call_once',side_effect=call),patch('workflows.daily_blog.time.sleep') as sleep:
                self.assertEqual(runner('draft','',None,Path(tmp)),{'ok':True})
                sleep.assert_called_once_with(45)
            self.assertEqual(len(runner.calls),2)

    def test_denial_and_exhausted_budget_never_retry(self):
        for failure,budget in [('provider_access_denied',2),('provider_stream_interrupted',1)]:
            with tempfile.TemporaryDirectory() as tmp:
                runner=ModelRunner({'workflow':{'transient_retry':{'max_retries':1},'network_policy':{'max_cli_invocations_per_run':budget}}},Path(tmp))
                def fail(*args):
                    runner.calls.append({'failure_kind':failure})
                    raise ValueError('failed')
                with patch.object(runner,'_call_once',side_effect=fail),patch('workflows.daily_blog.time.sleep') as sleep:
                    with self.assertRaises(ValueError):runner('draft','',None,Path(tmp))
                    sleep.assert_not_called()

    def test_stream_failure_is_not_local_timeout(self):
        envelope={'error':'The stream was interrupted. Please continue.'}
        self.assertEqual(model_failure_kind(envelope), 'provider_stream_interrupted')
        self.assertEqual(model_failure_kind(envelope, 'INTERNAL (code 500): Internal error encountered.'), 'provider_internal_error')
        self.assertEqual(model_failure_kind({'error':'print timed out'}), 'provider_reported_timeout')

    def test_reviewed_queue_obeys_cache_scope_and_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);db=root/'db'
            (root/'data/normalized').mkdir(parents=True)
            record={'record_type':'webpage','text':'a'*1000}
            (root/'data/normalized/cached.json').write_text(json.dumps(record))
            with sqlite3.connect(db) as c:
                c.execute('CREATE TABLE documents(canonical_url TEXT, normalized_path TEXT, content_hash TEXT)')
                c.execute('INSERT INTO documents VALUES(?,?,?)',('https://example.com/cached','data/normalized/cached.json',digest(record)))
            pages=[{'url':'https://example.com/'+name,'published_at':'2024-01-01T00:00:00+00:00'} for name in ['cached','one','two','three']]
            pages.insert(0,{'url':'https://evil.example/article','published_at':'2024-01-01T00:00:00+00:00'})
            cfg={'collector':{'discovery':{'max_pages_per_run':4,'max_pages_per_host':2,'official_url_prefixes':['https://example.com/'],'reviewed_pages':pages}}}
            with patch('collectors.dependency_evidence.select_sources',return_value=[]):
                result=select_relationship_sources(cfg,root,db,datetime.now(timezone.utc))
            self.assertEqual([r['url'] for r in result],['https://example.com/one','https://example.com/two'])
            self.assertTrue(all(r['obey_robots_txt'] for r in result))

    def test_old_supplier_cannot_replace_acquired_internal_relationship(self):
        source={'id':'s','url':'https://example.com/old','date':'2024-01-01','title':'Old announcement','publisher':'Issuer','text':'Mynaric supplied terminals.','hash':'b'*64}
        bi={'zh':'历史供应','en':'Historical supply'}
        row={'company':'rocket_lab','direction':'upstream','kind':'supplier','status':'historical','entity':{'zh':'Mynaric','en':'Mynaric'},'role':bi,'claim':bi,'watch':bi,'quote':source['text'],'source_id':'s'}
        class Runner:
            calls=[]
            def __call__(self,stage,prompt,schema,directory):
                candidate={'relationships':[row]}
                return candidate if stage=='extract' else {'approved':True,'issues':[],'source_sha256':digest([source]),'candidate_sha256':digest(candidate)}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);output=root/'snapshot.json'
            original=(REPO/'web/data/company_dependencies.json').read_bytes();output.write_bytes(original)
            with patch('workflows.dependencies.cached_documents',return_value=[source]):
                result=run({'workflow':{'output':str(output)}},root,root/'db',root/'run',True,Runner())
            self.assertEqual(result['items_new'],0)
            self.assertEqual(output.read_bytes(),original)
