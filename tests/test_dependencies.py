import copy
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from workflows.dependencies import bind, digest, cached_documents, run, REPO


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
