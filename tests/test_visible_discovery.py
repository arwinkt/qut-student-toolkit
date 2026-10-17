"""Offline browser-visible discovery and partial reconciliation contracts."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qut_toolkit.client import CanvasError
from qut_toolkit.config import Config
from qut_toolkit.sync import sync_course
from qut_toolkit.recording_sync import course_sources

BASE = 'https://canvas.qut.edu.au'


def inventory():
    return {'course_id': '7', 'complete': False, 'bounded': True,
            'modules': [{'id': '3', 'title': 'Week one'}],
            'resources': [
                {'kind': 'page', 'id': 'lesson', 'title': 'Lesson', 'url': BASE+'/courses/7/pages/lesson?token=SECRET', 'module_ids': ['3']},
                {'kind': 'file', 'id': '9', 'title': 'Notes', 'url': BASE+'/courses/7/files/9/download?token=SECRET', 'module_ids': ['3']},
                {'kind': 'assignment', 'id': '4', 'title': 'Task', 'url': BASE+'/courses/7/assignments/4', 'module_ids': ['3']},
                {'kind': 'page', 'id': 'bad', 'url': BASE+'/courses/8/pages/bad'},
                {'kind': 'file', 'id': '10', 'url': 'https://evil.invalid/courses/7/files/10'}],
            'pages': [{'url': BASE+'/courses/7/modules?token=SECRET', 'outcome': 'observed'}]}


class DeniedListings:
    base_url = BASE
    def __init__(self): self.calls = []
    def list(self, path):
        if '/announcements?' in path or '/external_tools?' in path: return []
        raise CanvasError('access', 'SECRET', 403)
    def get(self, path):
        self.calls.append(path)
        if path.endswith('/courses/7'): return {'name': 'Unit'}
        if '/pages/lesson' in path:
            return {'page_id': 8, 'title': 'Lesson', 'body': '<iframe src="https://echo360.net.au/lesson/abc"></iframe>'}
        if '/assignments/4' in path: return {'id': 4, 'name': 'Task'}
        if '/files/9' in path: return {'id': 9, 'filename': 'notes.txt', 'url': BASE+'/files/9/download'}
        raise AssertionError(path)
    def download(self, url): return b'ordinary file'


class IntegrationTests(unittest.TestCase):
    def test_opt_in_inventory_harvest_and_reconcile(self):
        c = DeniedListings()
        with tempfile.TemporaryDirectory() as d:
            result = sync_course(c, 7, Config(root=Path(d)), browser_inventory=lambda cid: inventory())
            unit = Path(d)/'units/course-7'
            self.assertFalse(result['complete'])
            self.assertTrue((unit/'resources/file-9.txt').exists())
            self.assertTrue((unit/'assignments/assignment-4.md').exists())
            self.assertIn('Lesson', (unit/'modules/module-3/INDEX.md').read_text())
            report = json.loads((unit/'visible-reconciliation.json').read_text())
            self.assertFalse(report['complete'])
            self.assertEqual(len(report['resources']), 3)
            self.assertTrue(all(r['saved'] for r in report['resources']))
            self.assertEqual(report['resources'][0]['module_ids'], ['3'])
            self.assertTrue((unit/'visible-reconciliation.md').exists())
            for p in unit.rglob('*'):
                if p.is_file(): self.assertNotIn(b'SECRET', p.read_bytes())
            # A later bounded view must not claim retained but unseen entries absent.
            sync_course(c, 7, Config(root=Path(d)), browser_inventory=lambda cid: {'course_id':cid, 'resources':[], 'modules':[], 'pages':[], 'bounded':True})
            report = json.loads((unit/'visible-reconciliation.json').read_text())
            self.assertTrue(any(r['observation']=='not_observed_unknown' for r in report['resources']))

    def test_forbidden_file_diagnosed_not_downloaded(self):
        class DeniedFile(DeniedListings):
            def get(self, path):
                if '/files/9' in path: raise CanvasError('access', 'SECRET', 403)
                return super().get(path)
        with tempfile.TemporaryDirectory() as d:
            result = sync_course(DeniedFile(), 7, Config(root=Path(d)), browser_inventory=lambda cid: inventory())
            self.assertFalse(result['complete'])
            report = json.loads((Path(d)/'units/course-7/visible-reconciliation.json').read_text())
            file = next(r for r in report['resources'] if r['kind']=='file')
            self.assertFalse(file['saved'])
            self.assertEqual(file['access'], 'api_forbidden_visible_link_only')

    def test_recording_sources_opt_in_seeds_visible_pages(self):
        sources, errors = course_sources(DeniedListings(), 7, browser_inventory=lambda cid: inventory())
        self.assertTrue(any(s['source_url'].endswith('/pages/lesson') for s in sources))
        self.assertTrue(any(e['stage']=='browser inventory' for e in errors))

    def test_retained_page_is_matched_when_api_now_forbidden(self):
        class LaterForbidden(DeniedListings):
            denied=False
            def get(self,path):
                if self.denied and '/pages/lesson' in path: raise CanvasError('access','denied',403)
                return super().get(path)
        with tempfile.TemporaryDirectory() as d:
            client=LaterForbidden();cfg=Config(root=Path(d))
            sync_course(client,7,cfg,browser_inventory=lambda cid:inventory())
            client.denied=True
            sync_course(client,7,cfg,browser_inventory=lambda cid:inventory())
            report=json.loads((Path(d)/'units/course-7/visible-reconciliation.json').read_text())
            pages=[r for r in report['resources'] if r['kind']=='page']
            self.assertEqual(len(pages),1)
            self.assertTrue(pages[0]['saved'])
            self.assertEqual(pages[0]['access'],'api_forbidden_visible_link_only')

    def test_reconciliation_does_not_claim_deleted_file_saved(self):
        from qut_toolkit.visible import normalize_inventory, reconciliation
        visible=normalize_inventory(inventory(),BASE,7)
        entries={'file:9':{'path':'resources/file-9.txt','metadata':{'id':'9'}}}
        report=reconciliation(visible,entries,{},[],saved_paths=set())
        self.assertFalse(next(r for r in report['resources'] if r['kind']=='file')['saved'])

    def test_callback_failure_is_partial_and_redacted(self):
        def fail(cid): raise RuntimeError('https://private.invalid/?token=SECRET')
        with tempfile.TemporaryDirectory() as d:
            result = sync_course(DeniedListings(), 7, Config(root=Path(d)), browser_inventory=fail)
            self.assertFalse(result['complete'])
            self.assertNotIn('SECRET', json.dumps(result))
            self.assertTrue(any(e['section']=='browser inventory' for e in result['errors']))


class FakeResponse:
    status = 200


class FakeLocator:
    def __init__(self, page): self.page = page
    def count(self): return 1 if self.page.url.endswith('/modules') else 0
    def nth(self, n): return self
    def click(self, **kwargs): self.page.expanded += 1


class FakePage:
    def __init__(self): self.url=''; self.visits=[]; self.expanded=0; self.closed=False
    def route(self, pattern, handler): self.guard=handler
    def goto(self, url, **kwargs):
        self.url=url; self.visits.append(url); return FakeResponse()
    def locator(self, selector):
        assert 'expand_module_link' in selector
        return FakeLocator(self)
    def evaluate(self, script):
        if self.url.endswith('/modules'):
            return {'modules':[{'id':'3','title':'Week one'}], 'links':[
                {'url':BASE+'/courses/7/pages/lesson','title':'Lesson','module_ids':['3']},
                {'url':BASE+'/courses/7/modules?page=2','title':'Next','next':True},
                {'url':BASE+'/courses/7/pages/lesson/edit','title':'Edit'},
                {'url':BASE+'/courses/8/pages/other','title':'Other'},
                {'url':'https://evil.invalid/courses/7/pages/no','title':'No'}]}
        if '/pages/lesson' in self.url:
            return {'modules':[], 'links':[{'url':BASE+'/courses/7/files/9/download?token=SECRET','title':'Notes'}]}
        return {'modules':[], 'links':[]}
    def close(self): self.closed=True


class FakeContext:
    def __init__(self): self.page=FakePage()
    def new_page(self): return self.page


class FakeSession:
    base_url=BASE
    timeout=1
    def __init__(self): self.context=FakeContext()


class VisibleTests(unittest.TestCase):
    def test_real_helper_uses_context_safe_traversal_and_closes_only_own_tab(self):
        from qut_toolkit.visible import browser_inventory
        session=FakeSession()
        result=browser_inventory(session, 7, max_pages=10)
        page=session.context.page
        self.assertTrue(page.closed)
        self.assertEqual(page.expanded, 1)
        self.assertIn(BASE+'/courses/7/modules?page=2', page.visits)
        self.assertTrue(all('/courses/7' in u and '/edit' not in u and 'evil' not in u for u in page.visits))
        self.assertFalse(any('/download' in u for u in page.visits))
        file=next(r for r in result['resources'] if r['kind']=='file')
        self.assertEqual(file['id'],'9')
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertFalse(result['complete'])
        self.assertTrue(result['pages'])

    def test_unscoped_file_reference_and_observable_module_item_id(self):
        from qut_toolkit.visible import normalize_inventory
        raw={'course_id':'7','resources':[{'url':BASE+'/files/9/download?module_item_id=44&token=SECRET', 'title':'Notes'}]}
        result=normalize_inventory(raw,BASE,7)
        self.assertEqual(result['resources'][0]['id'],'9')
        self.assertEqual(result['resources'][0]['module_item_id'],'44')
        self.assertNotIn('SECRET',json.dumps(result))

    def test_forbidden_response_is_not_harvested(self):
        from qut_toolkit.visible import browser_inventory
        session=FakeSession()
        page=session.context.page
        def forbidden(url, **kwargs):
            page.url=url
            response=FakeResponse();response.status=403
            return response
        page.goto=forbidden
        result=browser_inventory(session,7)
        self.assertEqual(result['resources'],[])
        self.assertTrue(all(p['outcome']=='forbidden' for p in result['pages']))
        self.assertTrue(page.closed)

    def test_invalid_callback_course_is_rejected(self):
        from qut_toolkit.visible import normalize_inventory
        with self.assertRaises(ValueError): normalize_inventory({'course_id':'8'},BASE,7)

    def test_page_budget_is_explicit(self):
        from qut_toolkit.visible import browser_inventory
        result=browser_inventory(FakeSession(), 7, max_pages=1)
        self.assertTrue(result['bounded'])
        self.assertEqual(len(result['pages']), 1)

    def test_browser_guard_blocks_actions_cross_course_lti_and_nonread_requests(self):
        from qut_toolkit.visible import browser_inventory
        from types import SimpleNamespace
        session=FakeSession()
        browser_inventory(session,7,max_pages=1)
        class Route:
            def __init__(self,url,method='GET'):
                self.request=SimpleNamespace(url=url,method=method,is_navigation_request=lambda:True)
                self.aborted=False;self.continued=False
            def abort(self): self.aborted=True
            def continue_(self): self.continued=True
        for url,method in [(BASE+'/courses/8/pages/no','GET'),
                           (BASE+'/courses/7/pages/lesson/edit','GET'),
                           (BASE+'/courses/7/external_tools/55','GET'),
                           (BASE+'/courses/7/files/9/download','GET'),
                           (BASE+'/courses/7/pages/lesson','POST')]:
            route=Route(url,method);session.context.page.guard(route)
            self.assertTrue(route.aborted,(url,method))
        route=Route(BASE+'/courses/7/pages/lesson')
        session.context.page.guard(route)
        self.assertTrue(route.continued)


if __name__=='__main__': unittest.main()
