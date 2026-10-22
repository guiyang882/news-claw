import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workflows.dependencies import bind, digest, cached_documents, run, REPO, merge_reviewed, MAX_RELATIONSHIPS_PER_COMPANY


class DependenciesWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.doc={'id':'s1','url':'https://blogs.nvidia.com/blog/test/','date':'2026-10-01',
                  'title':'Official relationship','publisher':'NVIDIA','text':'NVIDIA supplies the cloud platform.','hash':'a'*64}
        bi={'zh':'供应关系','en':'Supply relationship'}
        self.row={'company':'google','direction':'upstream','kind':'supplier','status':'disclosed',
                  'entity':{'zh':'英伟达','en':'NVIDIA'},'role':bi,'claim':bi,'watch':bi,'source_id':'s1','quote':self.doc['text']}

    def test_exact_quote_and_company_boundaries(self):
        rows=bind([self.row],[self.doc],'2026-10-15')
        self.assertEqual(rows[0][0],'google')
        for change in ({'quote':'Invented partnership.'},{'company':'other'},{'source_id':'unknown'},{'direction':'peer'}):
            with self.assertRaises((ValueError,KeyError)):
                bind([{**self.row,**change}],[self.doc],'2026-10-15')

    def test_growing_reviewed_graph_can_cross_old_twelve_row_limit(self):
        snapshot=json.loads((REPO/'web/data/company_dependencies.json').read_text())
        snapshot['companies']['google']['relationships']=[]
        bound=[]
        for index in range(17):
            row=copy.deepcopy(self.row)
            row['entity']={'zh':f'测试关系{index}','en':f'Fixture {index}'}
            bound.extend(bind([row],[self.doc],'2026-10-15'))
        result,count,deferred=merge_reviewed(snapshot,bound,'2026-10-15')
        self.assertEqual(count,17);self.assertFalse(deferred)
        self.assertEqual(len(result['companies']['google']['relationships']),17)
        self.assertEqual(snapshot['companies']['google']['relationships'],[])

    def test_capacity_preserves_old_rows_updates_existing_and_does_not_block_peers(self):
        snapshot=json.loads((REPO/'web/data/company_dependencies.json').read_text())
        rows=[]
        for index in range(MAX_RELATIONSHIPS_PER_COMPANY):
            row=copy.deepcopy(self.row);row['entity']={'zh':f'测试{index}','en':f'Fixture {index}'}
            rows.extend(bind([row],[self.doc],'2026-10-15'))
        snapshot['companies']['google']['relationships']=[row for _,row in rows]
        pending=bind([self.row,{**self.row,'company':'amazon'}],[self.doc],'2026-10-15')
        update=copy.deepcopy(rows[0]);update[1]['claim']['en']='Updated supported fixture'
        result,count,deferred=merge_reviewed(snapshot,[*pending,update],'2026-10-15')
        self.assertEqual(count,2);self.assertEqual(len(deferred),1)
        self.assertEqual(deferred[0]['company'],'google')
        self.assertEqual(len(result['companies']['google']['relationships']),MAX_RELATIONSHIPS_PER_COMPANY)
        self.assertEqual(result['companies']['google']['relationships'][-1]['claim']['en'],'Updated supported fixture')

    def test_newer_disclosure_is_never_replaced_by_recovery(self):
        snapshot=json.loads((REPO/'web/data/company_dependencies.json').read_text())
        bound=bind([self.row],[self.doc],'2026-10-15')
        newer=copy.deepcopy(bound[0][1]);newer['evidence'][0]['date']='2026-10-16'
        snapshot['companies']['google'].update(relationships=[newer],reviewed_on='2026-10-17')
        result,count,deferred=merge_reviewed(snapshot,bound,'2026-10-15')
        self.assertEqual(count,0);self.assertFalse(deferred)
        self.assertEqual(result,snapshot)

    def test_capacity_deferral_retains_approved_candidate_and_publishes_other_company(self):
        raw={'relationships':[self.row,{**self.row,'company':'amazon'}]}
        document=self.doc
        class Runner:
            calls=[]
            def __call__(self,stage,prompt,schema,directory):
                return raw if stage=='extract' else {'approved':True,'issues':[],
                    'source_sha256':digest([document]),'candidate_sha256':digest(raw)}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'published.json'
            original=json.loads((REPO/'web/data/company_dependencies.json').read_text())
            template=original['companies']['google']['relationships'][0]
            original['companies']['google']['relationships']=[{**copy.deepcopy(template),'id':str(i),
                'entity':{'zh':f'测试{i}','en':f'Fixture {i}'}} for i in range(MAX_RELATIONSHIPS_PER_COMPANY)]
            output.write_text(json.dumps(original))
            with patch('workflows.dependencies.cached_documents',return_value=[document]):
                result=run({'workflow':{'output':str(output)}},root,root/'db',root/'run',True,Runner())
            self.assertFalse(result['success']);self.assertTrue(result['needs_attention'])
            self.assertEqual(result['business_status'],'capacity_needs_review')
            self.assertEqual(result['items_new'],1);self.assertEqual(result['deferred_count'],1)
            deferred=json.loads((root/'run/deferred-relationships.json').read_text())
            self.assertEqual(deferred['candidate_sha256'],digest(raw))
            saved=json.loads(output.read_text())
            self.assertEqual(saved['companies']['google'],original['companies']['google'])

    def test_rejected_review_preserves_output_and_daily_reservation(self):
        class Runner:
            calls=[]
            def __call__(self,stage,prompt,schema,directory):
                return {'relationships':[self.row]} if stage=='extract' else {'approved':False,'issues':['Unsupported'], 'source_sha256':'wrong','candidate_sha256':'wrong'}
        runner=Runner();runner.row=self.row
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'published.json'
            original=(REPO/'web/data/company_dependencies.json').read_bytes();output.write_bytes(original)
            config={'workflow':{'output':str(output)}}
            with patch('workflows.dependencies.cached_documents',return_value=[self.doc]):
                with self.assertRaises(ValueError):run(config,root,root/'db',root/'run',True,runner)
                self.assertEqual(output.read_bytes(),original)
                self.assertEqual(run(config,root,root/'db',root/'run',True,runner)['business_status'],'daily_attempt_already_reserved')

    def test_approved_review_requires_bound_hashes_and_updates_atomic_snapshot(self):
        class Runner:
            calls=[]
            def __call__(self,stage,prompt,schema,directory):
                raw={'relationships':[self.row]}
                return raw if stage=='extract' else {'approved':True,'issues':[], 'source_sha256':digest([self.doc]),'candidate_sha256':digest(raw)}
        runner=Runner();runner.row=self.row;runner.doc=self.doc
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);output=root/'published.json'
            output.write_bytes((REPO/'web/data/company_dependencies.json').read_bytes())
            with patch('workflows.dependencies.cached_documents',return_value=[self.doc]):
                result=run({'workflow':{'output':str(output)}},root,root/'db',root/'run',True,runner)
            self.assertEqual(result['items_new'],1)
            rows=json.loads(output.read_text())['companies']['google']['relationships']
            self.assertEqual(sum(r['entity']['en']=='NVIDIA' for r in rows),1)
