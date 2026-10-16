import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from qut_toolkit.recording_sync import course_sources, write_transcript_index
from qut_toolkit.client import CanvasError

class RestrictedCourse:
    base_url='https://canvas.qut.edu.au'
    def list(self,path):
        if '/external_tools?' in path:
            return [{'id':1,'name':'Echo360','course_navigation':{'enabled':True,'visibility':'members'}}, {'id':2,'name':'Echo360 Analytics','course_navigation':{'enabled':True,'visibility':'admins'}}, {'id':3,'name':'Echo360 Content Embed'}]
        if '/pages?' in path:
            raise CanvasError('http','pages disabled',404)
        if '/items?' in path:
            return [{'type':'Page','page_url':'lecture','title':'Lecture'},{'type':'Page','page_url':'lecture','title':'Duplicate'}]
        if '/modules?' in path:
            return [{'id':4}]
        raise AssertionError(path)
    def get(self,path):
        return {'title':'Lecture','body':'<iframe src="https://echo360.net.au/ui/player/synthetic?secureLinkAccessDataId=DO_NOT_STORE"></iframe>'}

class RecordingSyncTests(unittest.TestCase):
    def test_restricted_pages_fallback_filters_admin_tools(self):
        sources,errors=course_sources(RestrictedCourse(),7)
        self.assertEqual(len(sources),2)
        self.assertEqual(len(errors),1)
        self.assertEqual(errors[0]['kind'],'module_only_coverage')
        self.assertNotIn('DO_NOT_STORE',json.dumps(sources))
        self.assertNotIn('Analytics',json.dumps(sources))

    def test_bounded_does_not_advance_success(self):
        with tempfile.TemporaryDirectory() as d:
            result={'source_url':'https://canvas.qut.edu.au/courses/7/pages/a','title':'A','status':'exported','warnings':[],'exports':[]}
            summary=write_transcript_index(d,7,[result],bounded=True)
            self.assertFalse(summary['complete'])
            manifest=json.loads((Path(d)/'units/course-7/lectures/manifest.json').read_text())
            self.assertIsNone(manifest['last_success'])

if __name__=='__main__':unittest.main()
