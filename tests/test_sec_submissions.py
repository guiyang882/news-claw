"""Offline SEC parsing and source-boundary checks."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scrapy.http import Request, TextResponse
from collectors.sec_submissions import parse_submissions
from collectors.news import NewsSpider, validate

CIK = 1679788
URL = 'https://data.sec.gov/submissions/CIK0001679788.json'


def fixture():
    stamp = datetime.now(timezone.utc).isoformat()
    return {'cik': CIK, 'name': 'Coinbase Global, Inc.', 'filings': {'recent': {
        'accessionNumber': ['0001679788-26-000101', '0001679788-26-000102'],
        'filingDate': [stamp[:10]] * 2, 'reportDate': [stamp[:10]] * 2,
        'acceptanceDateTime': [stamp] * 2, 'form': ['8-K', '4'],
        'primaryDocument': ['coin-test.htm', 'ownership.xml']}}}


def task():
    return {'collector': {'sources': [{'type':'sec_submissions','name':'SEC EDGAR Coinbase',
        'url':URL,'cik':CIK,'forms':['8-K'],'obey_robots_txt':True}]}, 'options': {'lookback_hours':720}}


class SecSubmissionsTests(unittest.TestCase):
    def test_metadata_keeps_real_acceptance_time_and_filters_insider_forms(self):
        source=fixture();rows=parse_submissions(source,CIK,['8-K'])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['record_type'],'sec_filing')
        self.assertIn('/1679788/000167978826000101/coin-test.htm',rows[0]['canonical_url'])
        self.assertIn('filing text has not been retrieved',rows[0]['text'])
        self.assertEqual(datetime.fromisoformat(rows[0]['published_at']).date(),datetime.now(timezone.utc).date())

    def test_wrong_company_misaligned_columns_and_unsafe_document_are_rejected(self):
        for change in ('company','columns','document','time'):
            data=fixture();recent=data['filings']['recent']
            if change=='company':data['cik']=1
            if change=='columns':recent['form'].pop()
            if change=='document':recent['primaryDocument'][0]='../../other.htm'
            if change=='time':recent['acceptanceDateTime'][0]='2026-10-01T12:00:00'
            with self.assertRaises(ValueError):parse_submissions(data,CIK,['8-K'])

    def test_sec_configuration_requires_exact_api_endpoint_and_robots(self):
        config=task();validate(config)
        for key,value in (('url','https://example.com/api'),('obey_robots_txt',False),('forms',[])):
            bad=deepcopy(config);bad['collector']['sources'][0][key]=value
            with self.assertRaises(ValueError):validate(bad)

    def test_scrapy_parser_archives_json_without_fetching_filing_documents(self):
        config=task();source=config['collector']['sources'][0]
        with tempfile.TemporaryDirectory() as tmp:
            spider=NewsSpider(config,Path(tmp))
            response=TextResponse(URL,body=json.dumps(fixture()).encode(),encoding='utf-8',
                                  request=Request(URL,meta={'source':source}),headers={'Content-Type':'application/json'})
            rows=list(spider.parse_source(response))
            self.assertEqual(len(rows),1);self.assertEqual(spider.requests_made,0)
            self.assertTrue(rows[0]['raw_path'].endswith('.json'))
            self.assertTrue((Path(tmp)/rows[0]['raw_path']).is_file())
