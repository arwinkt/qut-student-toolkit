"""Regressions from live QUT integration and interrupted-sync review."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from qut_toolkit.client import CanvasError
from qut_toolkit.config import Config
from qut_toolkit.storage import Store
from qut_toolkit.sync import sync_course
from test_sync import FixtureClient


class IntegrationGuards(unittest.TestCase):
    def test_disabled_pages_still_shows_verified_assessments(self):
        class Disabled(FixtureClient):
            def list(self,path):
                if '/pages?' in path: raise CanvasError('http','disabled',404)
                return super().list(path)
        with tempfile.TemporaryDirectory() as d:
            r=sync_course(Disabled(),7,Config(root=Path(d)))
            self.assertFalse(r['complete'])
            self.assertTrue(r['assessment_complete'])
            self.assertIn('Quiz',(Path(d)/'units/course-7/findings.md').read_text())
            self.assertIn('released',(Path(d)/'units/course-7/findings.md').read_text())

    def test_unchanged_canvas_file_revision_avoids_download(self):
        class Versioned(FixtureClient):
            downloaded=0
            def get(self,path):
                result=super().get(path)
                if '/files/9' in path: result.update(updated_at='2026-01-01T00:00:00Z',size=15)
                return result
            def download(self,url):
                self.downloaded+=1
                return super().download(url)
        with tempfile.TemporaryDirectory() as d:
            c=Versioned();cfg=Config(root=Path(d))
            sync_course(c,7,cfg);sync_course(c,7,cfg)
            self.assertEqual(c.downloaded,1)

    def test_optin_notes_export_and_local_edit(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'library';notes=Path(d)/'vault'
            cfg=Config(root=root,notes_root=notes);c=FixtureClient()
            r=sync_course(c,7,cfg)
            path=notes/'qut-toolkit/course-7/pages/page-8.md'
            self.assertTrue(path.exists())
            self.assertEqual(r['notes_export'],'exported')
            path.write_text('my notes')
            c.body='<p>updated</p>'
            sync_course(c,7,cfg)
            self.assertEqual(path.read_text(),'my notes')

    def test_course_navigation_recordings_link_to_stable_index(self):
        class Navigation(FixtureClient):
            def list(self,path):
                if '/external_tools?' in path:
                    return [{'id':5,'name':'Echo360','course_navigation':{'enabled':True,'visibility':'members'}}]
                return super().list(path)
        with tempfile.TemporaryDirectory() as d:
            r=sync_course(Navigation(),7,Config(root=Path(d)))
            self.assertEqual(r['recordings'],1)
            self.assertTrue((Path(d)/'units/course-7/lectures/INDEX.md').exists())
            self.assertIn('lectures/INDEX.md',(Path(d)/'units/course-7/INDEX.md').read_text())

    def test_video_resources_are_opt_in(self):
        class Media(FixtureClient):
            downloads=0
            def get(self,path):
                result=super().get(path)
                if '/files/9' in path:
                    result.update(filename='lecture.mp4',size=1000,**{'content-type':'video/mp4'})
                return result
            def download(self,url):
                self.downloads+=1
                return b'synthetic video'
        with tempfile.TemporaryDirectory() as d:
            c=Media();result=sync_course(c,7,Config(root=Path(d)))
            self.assertEqual(c.downloads,0)
            self.assertTrue(any('audio/video' in x.get('reason','') for x in result['skipped']))
            sync_course(c,7,Config(root=Path(d),include_media=True))
            self.assertEqual(c.downloads,1)

    def test_oversized_document_is_reported_not_downloaded(self):
        class Large(FixtureClient):
            def get(self,path):
                result=super().get(path)
                if '/files/9' in path:result.update(size=9999)
                return result
            def download(self,url):raise AssertionError('oversized file should not be downloaded')
        with tempfile.TemporaryDirectory() as d:
            result=sync_course(Large(),7,Config(root=Path(d),max_file_bytes=100))
            self.assertFalse(result['complete'])
            self.assertTrue(any(x['kind']=='size_limit' for x in result['errors']))

    def test_library_internal_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            s=Store(d)
            with patch('qut_toolkit.storage.is_link', side_effect=lambda p:Path(p).name=='pages'):
                with self.assertRaises(ValueError): s.put('page:1','pages/page-1.md','a')

    def test_intermediate_checkpoint_exists_during_download(self):
        with tempfile.TemporaryDirectory() as d:
            class Checkpoint(FixtureClient):
                def download(self,url):
                    state=json.loads((Path(d)/'units/course-7/manifest.json').read_text())
                    self.assertion=not state['complete'] and 'page:8' in state['entries']
                    return super().download(url)
            c=Checkpoint();sync_course(c,7,Config(root=Path(d)))
            self.assertTrue(c.assertion)

if __name__=='__main__':unittest.main()
