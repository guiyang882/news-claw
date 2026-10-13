from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import hashlib
import sqlite3
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from workflows.company_watch import run, content_digest, validate_bundle, cached_news
from workflows import daily_blog as models

ROOT = Path(__file__).resolve().parents[1]


class Runner:
    def __init__(self, fail=False):self.calls=[];self.fail=fail
    def __call__(self, stage, prompt, schema, directory):
        self.calls.append({'provider':'agy' if stage=='draft' else 'codex', 'usage':{'total_tokens':1000}})
        if self.fail:raise RuntimeError('Model unavailable')
        if stage=='draft':
            packet=json.loads(prompt.split('Input: ',1)[1])
            lang={'headline':'Issuer announcement','summary':'The issuer announced a product; adoption is unknown.',
                  'developments':['The issuer announced a product.'],'catalysts':['Check adoption.'],'risks':['No independent adoption data.']}
            return {'company':packet['company'],'sentiment':'uncertain','confidence':0.5,
                    'evidence_event_ids':[packet['events'][0]['id']],'zh':lang,'en':lang}
        packet=json.loads(prompt[prompt.index('{'):])
        return {'approved':True,'issues':[],'source_sha256':packet['source_sha256'],
                'analysis_sha256':packet['analysis_sha256']}


class RepairRunner(Runner):
    def __init__(self, reject_again=False):
        super().__init__();self.stages=[];self.reject_again=reject_again

    def __call__(self, stage, prompt, schema, directory):
        self.stages.append(stage)
        if stage=='revise':
            self.calls.append({'provider':'codex','usage':{'total_tokens':1000}})
            packet=json.loads(prompt.split('Input: ',1)[1])
            analysis=packet['analysis']
            for language in ('zh','en'):
                analysis[language]['summary']='The issuer announced a product; the supplied excerpt does not establish adoption.'
            return analysis
        result=super().__call__(stage,prompt,schema,directory)
        if stage=='review' or (stage=='review_revised' and self.reject_again):
            result.update(approved=False,issues=['Narrow the claim to the supplied excerpt.'])
        return result


class CompanyWatchWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        schemas=self.root/'config/schemas';schemas.mkdir(parents=True)
        for name in ('company-brief.schema.json','company-brief-review.schema.json'):
            (schemas/name).write_bytes((ROOT/'config/schemas'/name).read_bytes())
        self.now=datetime.now(timezone.utc)-timedelta(hours=4)
        self.config=json.loads((ROOT/'config/tasks/company-google-brief.json').read_text())
        self.config['workflow']['state_root']=str(self.root/'site')
        self.write_news('google')

    def write_news(self,company, suffix=''):
        stamp=self.now.isoformat()
        bundle=validate_bundle({'schema_version':1,'generated_at':stamp,
            'sources':[{'id':'official','name':'Issuer','import_mode':'offline_import'}],
            'events':[{'id':company+str(i)+suffix,'company':company,'title':'Issuer announcement',
                       'source_id':'official','source_url':f'https://example.com/{company}/{i}',
                       'published_at':stamp,'observed_at':stamp} for i in range(2)]})
        path=self.root/'site/company_news'/f'{company}.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(bundle));return path

    def call(self,runner,company='google',now=None,execute=True):
        config=deepcopy(self.config);config['workflow']['company']=company
        return run(config,self.root,self.root/'unused.db',self.root/'run'/company,now=now or self.now,
                   execute=execute,model_runner=runner)

    def test_preview_and_missing_material_never_invoke_model(self):
        runner=Runner()
        self.assertEqual(self.call(runner,execute=False)['business_status'],'preview')
        self.assertEqual(self.call(runner,'amazon')['business_status'],'insufficient_evidence')
        self.assertEqual(runner.calls,[])

    def test_real_schema_accepts_fractional_confidence_and_enforces_bounds(self):
        schema=json.loads((ROOT/'config/schemas/company-brief.schema.json').read_text())
        runner=Runner();self.call(runner)
        value=json.loads((self.root/'site/company_briefs/google.json').read_text())['analysis']
        models.validate_shape(value,schema)
        for invalid in (True, -0.1, 1.1, float('nan'), '0.5'):
            bad=deepcopy(value);bad['confidence']=invalid
            with self.assertRaises(ValueError):models.validate_shape(bad,schema)
        value['en']['summary']='x'*401
        with self.assertRaises(ValueError):models.validate_shape(value,schema)

    def test_cached_news_deduplicates_links_and_rejects_changed_documents(self):
        db=self.root/'cache.sqlite3';normalized=self.root/'data/normalized';normalized.mkdir(parents=True)
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE documents(id TEXT,published_at TEXT,fetched_at TEXT,source_json TEXT,normalized_path TEXT,content_hash TEXT)')
            for i in range(3):
                record={'published_at':self.now.isoformat(),'title':'Issuer announcement','text':'Issuer claim',
                        'record_type':'feed_entry','canonical_url':'https://example.com/announcement'}
                path=normalized/f'{i}.json';path.write_text(json.dumps(record))
                source={'name':'Issuer','url':self.config['workflow']['source_urls'][0] if i<2 else 'https://other.example/feed'}
                digest=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                connection.execute('INSERT INTO documents VALUES(?,?,?,?,?,?)',(str(i),self.now.isoformat(),self.now.isoformat(),json.dumps(source),str(path.relative_to(self.root)),digest))
        result=cached_news(self.config,self.root,db,now=self.now+timedelta(minutes=1))
        self.assertEqual(len(result['events']),1)
        self.assertEqual(result['events'][0]['company'],'google')
        with sqlite3.connect(db) as connection:
            for i in range(2):
                path=normalized/f'{i}.json';record=json.loads(path.read_text());record['record_type']='sec_filing'
                path.write_text(json.dumps(record))
                digest=hashlib.sha256(json.dumps(record,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
                connection.execute('UPDATE documents SET content_hash=? WHERE id=?',(digest,str(i)))
        result=cached_news(self.config,self.root,db,now=self.now+timedelta(minutes=1))
        self.assertEqual(result['events'][0]['tags'],['SEC filing · metadata only'])
        (normalized/'0.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash changed'):
            cached_news(self.config,self.root,db,now=self.now+timedelta(minutes=1))

    def test_publication_dedup_daily_cap_and_company_spacing(self):
        runner=Runner();result=self.call(runner)
        self.assertTrue(result['success']);self.assertEqual(len(runner.calls),2)
        self.assertTrue((self.root/'site/company_briefs/google.json').exists())
        self.assertEqual(self.call(runner)['business_status'],'unchanged_or_previously_attempted')
        self.write_news('google','new')
        self.assertEqual(self.call(runner)['business_status'],'daily_company_budget_reached')
        self.write_news('amazon')
        self.assertEqual(self.call(runner,'amazon')['business_status'],'staggered_budget_cooldown')
        self.assertEqual(self.call(Runner(),'amazon',self.now+timedelta(hours=2))['business_status'],'published')

    def test_failure_consumes_budget_and_preserves_published_snapshot(self):
        self.assertEqual(self.call(Runner())['business_status'],'published')
        path=self.root/'site/company_briefs/google.json';before=path.read_bytes()
        # A new day's new evidence may attempt once; a rejection retains the old publication.
        self.write_news('google','updated')
        runner=Runner(fail=True)
        self.assertFalse(self.call(runner,now=self.now+timedelta(days=1))['success'])
        self.assertEqual(path.read_bytes(),before)
        retry=Runner();self.assertEqual(self.call(retry,now=self.now+timedelta(days=1))['business_status'],
                                      'unchanged_or_previously_attempted')
        self.assertEqual(retry.calls,[])

    def test_codex_repairs_then_reviews_without_repeating_gemini(self):
        runner=RepairRunner();result=self.call(runner)
        self.assertEqual(result['business_status'],'published')
        self.assertEqual(runner.stages,['draft','review','revise','review_revised'])
        self.assertEqual(sum(c['provider']=='agy' for c in runner.calls),1)
        payload=json.loads((self.root/'site/company_briefs/google.json').read_text())
        self.assertTrue(payload['review']['approved'])
        self.assertEqual(payload['review']['analysis_sha256'],content_digest(payload['analysis']))
        self.assertEqual(payload['editor_model'],self.config['workflow']['reviewer']['model'])

    def test_second_rejection_stops_after_one_repair_and_preserves_old_brief(self):
        self.call(Runner());path=self.root/'site/company_briefs/google.json';before=path.read_bytes()
        self.write_news('google','updated');runner=RepairRunner(reject_again=True)
        result=self.call(runner,now=self.now+timedelta(days=1))
        self.assertFalse(result['success']);self.assertEqual(len(runner.calls),4)
        self.assertEqual(path.read_bytes(),before)

    def test_large_measured_usage_stops_remaining_new_company_calls(self):
        self.call(Runner())
        ledger=next((self.root/'data/runs/company-watch-budget').glob('*.json'))
        data=json.loads(ledger.read_text());data['attempts'][0]['agy_tokens']=100000;ledger.write_text(json.dumps(data))
        self.write_news('amazon');runner=Runner()
        self.assertEqual(self.call(runner,'amazon',self.now+timedelta(hours=2))['business_status'],
                         'daily_shared_budget_reached')
        self.assertEqual(runner.calls,[])

    def test_invalid_generation_still_records_real_token_usage(self):
        runner=models.ModelRunner(self.config,self.root)
        def start(command,**kwargs):
            kwargs['stdout'].write(json.dumps({'status':'SUCCESS','structured_output':{},
                                              'usage':{'total_tokens':100000}}).encode())
            kwargs['stdout'].flush()
            return Mock(returncode=0,poll=lambda:0)
        with patch.object(models.subprocess,'Popen',side_effect=start):
            with self.assertRaisesRegex(ValueError,'missing or unknown'):
                runner('draft','offline',ROOT/'config/schemas/company-brief.schema.json',self.root/'invalid')
        self.assertEqual(runner.calls[0]['usage']['total_tokens'],100000)
