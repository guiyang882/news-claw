import asyncio
import tempfile
import unittest
from pathlib import Path
from scrapy import Request
from scrapy.http import HtmlResponse
from scrapy.exceptions import IgnoreRequest
from collectors.news import RequestPolicy, policy_paths, load_state


class ChallengeCircuitTest(unittest.TestCase):
    def test_http_200_challenge_opens_persistent_source_circuit(self):
        class Spider:
            def fail(self,*args,**kwargs):pass
        with tempfile.TemporaryDirectory() as tmp:
            spider=Spider();spider.root=Path(tmp)
            request=Request('https://example.org/official-release')
            response=HtmlResponse(request.url,body=b'<html><title>Just a moment...</title>Verify you are human</html>',encoding='utf-8',request=request)
            with self.assertRaises(IgnoreRequest):
                asyncio.run(RequestPolicy(None).process_response(request,response,spider))
            path,_=policy_paths(spider.root,'example.org')
            self.assertEqual(load_state(path)['blocked'],'access challenge')
