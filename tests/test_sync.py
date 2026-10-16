"""Synthetic Canvas course: offline integration contract."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qut_toolkit.config import Config
from qut_toolkit.client import CanvasError
from qut_toolkit.sync import sync_course

class FixtureClient:
    base_url='https://canvas.qut.edu.au'
    body='<h2>Synthetic lesson</h2><p>Hello <a href="/courses/7/files/9/download">asset</a></p>'
    fail=False
    due='2026-10-20T00:00:00Z'
    def get(self,path):
        if path.endswith('/courses/7'): return {'id':7,'name':'Synthetic Unit'}
        if '/pages/' in path: return {'page_id':8,'url':'lesson','title':'Lesson','body':self.body,'html_url':self.base_url+'/courses/7/pages/lesson'}
        if '/files/9' in path:return {'id':9,'filename':'CON.txt','url':'https://cdn.invalid/signed?token=SECRET'}
        raise AssertionError(path)
    def list(self,path):
        if '/items' in path:return [{'id':10,'type':'Page','page_url':'lesson','title':'Lesson'}]
        if '/modules' in path:
            if self.fail:raise CanvasError('access','synthetic denied')
            return [{'id':3,'name':'Week 1'}]
        if '/pages' in path:return [{'page_id':8,'url':'lesson','title':'Lesson'}]
        if '/assignments' in path:return [{'id':4,'name':'Quiz','due_at':self.due,'points_possible':10,'html_url':self.base_url+'/courses/7/assignments/4','submission':{'score':0,'workflow_state':'graded','grade':'0','graded_at':'2026-10-01T00:00:00Z'}}]
        if '/files' in path:return []
        if '/announcements' in path:return []
        if '/external_tools?' in path:return []
        raise AssertionError(path)
    def download(self,url):return b'synthetic asset'

class SyncTests(unittest.TestCase):
    def test_offline_e2e_incremental_conflict_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            config=Config(root=Path(d)); c=FixtureClient()
            first=sync_course(c,7,config)
            self.assertTrue(first['complete'])
            unit=Path(d)/'units'/'course-7'
            self.assertTrue((unit/'modules'/'module-3'/'INDEX.md').exists())
            page=unit/'pages'/'page-8.md'
            self.assertIn('Synthetic lesson',page.read_text())
            self.assertNotIn('<h2>',page.read_text())
            self.assertTrue((unit/'resources'/'file-9.txt').exists())
            manifest=(unit/'manifest.json').read_text()
            self.assertNotIn('SECRET',manifest)
            second=sync_course(c,7,config)
            self.assertEqual(second['counts'].get('updated',0),0)
            page.write_text('my notes')
            c.body='<p>changed upstream</p>';c.due='2026-10-21T00:00:00Z'
            third=sync_course(c,7,config)
            self.assertEqual(page.read_text(),'my notes')
            self.assertGreater(third['counts'].get('conflict',0),0)
            self.assertTrue(any(x['kind']=='deadline_changed' for x in third['changes']))
            self.assertIn('released',(unit/'findings.md').read_text())
            self.assertTrue((Path(d)/'reports'/'latest-sync.json').exists())
    def test_failure_does_not_advance_success(self):
        with tempfile.TemporaryDirectory() as d:
            c=FixtureClient();cfg=Config(root=Path(d))
            sync_course(c,7,cfg)
            p=Path(d)/'units/course-7/manifest.json'
            before=json.loads(p.read_text())['last_success']
            c.fail=True
            result=sync_course(c,7,cfg)
            self.assertFalse(result['complete'])
            self.assertEqual(json.loads(p.read_text())['last_success'],before)

class CoverageTests(unittest.TestCase):
    def test_forbidden_listing_keeps_referenced_download_and_previous_snapshot(self):
        class Forbidden(FixtureClient):
            forbidden=False
            def list(self,path):
                if '/files?' in path and self.forbidden:
                    raise CanvasError('access','synthetic forbidden',403)
                return super().list(path)
        with tempfile.TemporaryDirectory() as d:
            c=Forbidden();cfg=Config(root=Path(d));sync_course(c,7,cfg)
            unit=Path(d)/'units/course-7'
            before=json.loads((unit/'manifest.json').read_text())
            c.forbidden=True;c.due='2027-01-01T00:00:00Z'
            result=sync_course(c,7,cfg)
            after=json.loads((unit/'manifest.json').read_text())
            self.assertFalse(result['complete'])
            self.assertIn('403',result['files_status'])
            self.assertEqual(after['last_success'],before['last_success'])
            self.assertEqual(after['assessment_snapshot'],before['assessment_snapshot'])
            self.assertTrue((unit/'resources/file-9.txt').exists())
            self.assertTrue(result['skipped'])
            self.assertIn('INCOMPLETE',(unit/'findings.md').read_text())
            self.assertEqual(result['changes'],[])

    def test_full_pages_not_only_modules_and_assignment_src_discovery(self):
        class Rich(FixtureClient):
            seen=[]
            def list(self,path):
                self.seen.append(path)
                if '/pages?' in path:
                    return super().list(path)+[{'page_id':12,'url':'unlinked','title':'Unlinked'}]
                if '/assignments?' in path:
                    self.assert_submission='include[]=submission' in path
                    items=super().list(path)
                    items[0]['description']='<p>Details<img src="/courses/7/files/11/preview"><a href="https://example.test/source?signature=SECRET">reference</a></p>'
                    return items
                return super().list(path)
            def get(self,path):
                if path.endswith('/pages/unlinked'):
                    return {'page_id':12,'url':'unlinked','title':'Unlinked','body':'<p>Unlinked page body</p>'}
                if path.endswith('/files/11'):
                    return {'id':11,'filename':'diagram.png','url':'https://cdn.invalid/eleven?token=SECRET'}
                return super().get(path)
        with tempfile.TemporaryDirectory() as d:
            c=Rich();sync_course(c,7,Config(root=Path(d)))
            unit=Path(d)/'units/course-7'
            self.assertTrue(c.assert_submission)
            self.assertTrue((unit/'pages/page-12.md').exists())
            self.assertTrue((unit/'resources/file-11.png').exists())
            self.assertIn('https://example.test/source',(unit/'assignments/assignment-4.md').read_text())
            for path in unit.rglob('*'):
                if path.is_file(): self.assertNotIn(b'SECRET',path.read_bytes(),str(path))
            self.assertNotIn('Unlinked page body',(unit/'INDEX.md').read_text())
            self.assertTrue(any('/modules/3/items?' in p for p in c.seen))

    def test_timezone_zero_manual_unreleased_and_undated(self):
        from qut_toolkit.reports import assessment_snapshot
        a={'id':1,'name':'Synthetic','due_at':'2026-10-20T00:00:00Z','submission':{'score':0,'workflow_state':'graded'}}
        snap=assessment_snapshot([a],FixtureClient.base_url,7,'Australia/Brisbane')['1']
        self.assertEqual(snap['score'],0)
        self.assertEqual(snap['grading_status'],'released')
        self.assertIn('10:00:00+10:00',snap['due_local'])
        a['post_manually']=True;a['due_at']=None
        snap=assessment_snapshot([a],FixtureClient.base_url,7,'UTC')['1']
        self.assertIsNone(snap['due_utc'])
        self.assertIsNone(snap['score'])
        self.assertEqual(snap['grading_status'],'ungraded/unreleased')

    def test_no_courses_report_is_not_clean(self):
        from qut_toolkit.reports import write_latest
        with tempfile.TemporaryDirectory() as d:
            report=write_latest(d,[])
            self.assertFalse(report['complete'])
            self.assertTrue(report['errors'])
            self.assertIn('No courses were checked',(Path(d)/'reports/latest-sync.md').read_text())

    def test_notes_export_is_explicit_and_namespaced(self):
        # Supersedes the scaffold's unsupported expectation: requested opt-in export
        # now exists, confined to a new qut-toolkit namespace, never a vault reorg.
        with tempfile.TemporaryDirectory() as d:
            notes=Path(d)/'notes'
            result=sync_course(FixtureClient(),7,Config(root=Path(d)/'library',notes_root=notes))
            self.assertEqual(result['notes_export'],'exported')
            self.assertTrue((notes/'qut-toolkit/course-7/pages/page-8.md').exists())

    def test_recording_adapter_receives_ephemeral_html_but_disk_has_durable_source(self):
        from unittest.mock import patch
        import types
        calls=[]
        def discover(html,source):
            calls.append((html,source))
            if 'iframe' not in html: return []
            return [{'id':'synthetic-recording','title':'Synthetic lecture','url':'https://echo.test/lesson/abc?token=SECRET','iframe_url':'https://echo.test/embed?token=SECRET','source_url':'https://bad.test/signed?token=SECRET'}]
        fake=types.ModuleType('qut_toolkit.echo');fake.discover_recordings=discover
        with tempfile.TemporaryDirectory() as d, patch.dict(sys.modules,{'qut_toolkit.echo':fake}):
            c=FixtureClient();c.body='<iframe src="https://echo.test/embed?token=SECRET"></iframe>'
            sync_course(c,7,Config(root=Path(d)))
            unit=Path(d)/'units/course-7'
            records=json.loads((unit/'recordings.json').read_text())
            self.assertEqual(records[0]['source_url'],c.base_url+'/courses/7/pages/lesson')
            self.assertEqual(records[0]['url'],'https://echo.test/lesson/abc')
            self.assertTrue(any('SECRET' in html for html,_ in calls))
            for path in unit.rglob('*'):
                if path.is_file(): self.assertNotIn(b'SECRET',path.read_bytes(),str(path))

if __name__=='__main__':unittest.main()
