"""Independent-review regression cases, synthetic inputs only."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from qut_toolkit.client import CanvasClient,CanvasError
from qut_toolkit.config import Config
from qut_toolkit.recording_sync import course_sources,write_transcript_index
from qut_toolkit.sync import sync_course
from qut_toolkit.transcripts import Cue,export_transcript
from test_sync import FixtureClient

class ReviewRegressions(unittest.TestCase):
    def test_successful_empty_pages_still_scans_module_tools(self):
        class Sources:
            base_url='https://canvas.qut.edu.au'
            def list(self,path):
                if '/pages?' in path or '/external_tools?' in path:return []
                if '/items?' in path:return [{'type':'ExternalTool','title':'Echo360 Lecture','html_url':self.base_url+'/courses/7/modules/items/8'}]
                if '/modules?' in path:return [{'id':1}]
                raise AssertionError(path)
        sources,errors=course_sources(Sources(),7)
        self.assertEqual(len(sources),1)
        self.assertEqual(errors,[])

    def test_empty_caption_attempt_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            report=write_transcript_index(d,7,[])
            self.assertFalse(report['complete'])

    def test_html_teaching_tool_with_password_input_is_not_login(self):
        from qut_toolkit.client import validate_download
        content=b'<html><title>Wi-Fi configuration generator</title><input type="password"></html>'
        client=CanvasClient(transport=lambda *a:(content,{'content-type':'text/html'}))
        self.assertEqual(client.download('https://canvas.qut.edu.au/files/1/download'),content)
        self.assertEqual(validate_download(content,'text/html'),content)
        with self.assertRaises(CanvasError):
            validate_download(content,'application/pdf')

    def test_login_html_download_rejected(self):
        c=CanvasClient(transport=lambda *a:(b'<html><title>Sign in</title><form><input type="password"></form></html>',{'Content-Type':'text/html'}))
        with self.assertRaises(CanvasError):c.download('https://cdn.invalid/resource')

    def test_document_html_mismatch_is_incomplete(self):
        class HTML(FixtureClient):
            def get(self,path):
                data=super().get(path)
                if '/files/9' in path:data.update({'content-type':'application/pdf'})
                return data
            def download(self,url):return b'<!DOCTYPE html><html><body>Gateway error</body></html>'
        with tempfile.TemporaryDirectory() as d:
            report=sync_course(HTML(),7,Config(root=Path(d)))
            self.assertFalse(report['complete'])
            self.assertFalse((Path(d)/'units/course-7/resources/file-9.txt').exists())

    def test_linked_canvas_pages_and_assessments_are_traversed(self):
        class Nested(FixtureClient):
            def get(self,path):
                if path.endswith('/pages/linked'):
                    return {'page_id':12,'url':'linked','title':'Linked','body':'<a href="/courses/7/pages/lesson">cycle</a><a href="/courses/7/assignments/13">Nested assessment</a>'}
                if path.endswith('/assignments/13'):
                    return {'id':13,'name':'Nested assessment','description':'<p>Instructions</p>'}
                result=super().get(path)
                if '/pages/lesson' in path:result['body']+='<a href="/courses/7/pages/linked">Next</a>'
                return result
        with tempfile.TemporaryDirectory() as d:
            result=sync_course(Nested(),7,Config(root=Path(d)))
            self.assertTrue((Path(d)/'units/course-7/pages/page-12.md').exists())
            self.assertTrue((Path(d)/'units/course-7/assignments/assignment-13.md').exists())
            self.assertLess(len(json.loads((Path(d)/'units/course-7/manifest.json').read_text())['entries']),30)

    def test_lecture_leaf_link_is_rejected(self):
        with tempfile.TemporaryDirectory() as d,patch('qut_toolkit.transcripts.is_link',return_value=True):
            with self.assertRaises(ValueError):export_transcript(d,'https://canvas.qut.edu.au/courses/7/pages/a','A',[Cue(0,1,'a')],{})

if __name__=='__main__':unittest.main()
