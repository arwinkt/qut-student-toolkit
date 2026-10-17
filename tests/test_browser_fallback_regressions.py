from pathlib import Path
import sys,unittest,json
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from qut_toolkit.visible import browser_inventory
from qut_toolkit.browser import BrowserSession
from qut_toolkit.client import CanvasError
from test_visible_discovery import FakeSession,FakePage,BASE

class ModulePage(FakePage):
    def evaluate(self, script):
        if self.url.endswith('/modules'):
            item={'url':BASE+'/courses/7/modules/items/99','title':'Lesson','module_ids':['3']}
            return {'modules':[{'id':'3','title':'Week 12'}],'links':[dict(item),dict(item)]}
        return {'modules':[],'links':[]}

class BrowserFallbackRegressions(unittest.TestCase):
    def test_module_item_redirect_is_read_without_lti_launch_and_cached(self):
        session=FakeSession();session.context.page=ModulePage();calls=[]
        def transport(url, headers, timeout):
            calls.append(url);return b'',{'location':BASE+'/courses/7/pages/lesson?private=SECRET'}
        session.transport=transport
        report=browser_inventory(session,7,max_pages=10)
        pages=[r for r in report['resources'] if r['kind']=='page']
        self.assertEqual(len(pages),1);self.assertEqual(pages[0]['id'],'lesson')
        self.assertEqual(pages[0]['module_item_id'],'99');self.assertEqual(pages[0]['module_ids'],['3'])
        self.assertEqual(len(calls),1);self.assertNotIn('SECRET',json.dumps(report))
        self.assertTrue(all('/external_tools/' not in u for u in session.context.page.visits))

    def test_external_module_redirect_is_never_followed(self):
        session=FakeSession();session.context.page=ModulePage();calls=[]
        def transport(url,headers,timeout):
            calls.append(url);return b'',{'location':'https://evil.invalid/?private=SECRET'}
        session.transport=transport
        report=browser_inventory(session,7,max_pages=10)
        self.assertTrue(all(u.startswith(BASE) for u in calls+session.context.page.visits))
        self.assertNotIn('evil.invalid',json.dumps(report));self.assertNotIn('SECRET',json.dumps(report))

    def test_browser_transport_keeps_retry_after_for_bounded_client_retry(self):
        session=BrowserSession.__new__(BrowserSession)
        response=SimpleNamespace(status=429,headers={'retry-after':'3'},ok=False,dispose=Mock())
        session.context=SimpleNamespace(request=SimpleNamespace(get=Mock(return_value=response)))
        with self.assertRaises(CanvasError) as raised:session.transport(BASE,{},1)
        self.assertEqual(raised.exception.retry_after,'3');response.dispose.assert_called_once()
