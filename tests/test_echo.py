"""Offline adapter discovery/security tests."""
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qut_toolkit.echo import discover_recordings, is_transcript_response, safe_canvas_url, AuthNeeded

class EchoTests(unittest.TestCase):
    def test_discovery(self):
        html = '''<iframe src="/courses/1/external_tools/retrieve?display=borderless&amp;url=https%3A%2F%2Fecho360.net.au%2Flti%2Flaunch"></iframe><video><track kind="captions" src="/caption.vtt" srclang="en" label="English"></video><a href="https://echo360.net.au/lesson/example">Lecture</a>'''
        items = discover_recordings(html, 'https://canvas.qut.edu.au/courses/1/pages/example')
        self.assertEqual(len(items),3)
        self.assertEqual({x['kind'] for x in items}, {'echo360','caption'})
        track = next(x for x in items if x['kind']=='caption')
        self.assertEqual(track['language'], 'en')
        self.assertEqual(track['url'],'https://canvas.qut.edu.au/caption.vtt')
    def test_dedupe_and_unrelated(self):
        self.assertEqual(discover_recordings('<a href="https://example.org">x</a>', 'https://canvas.qut.edu.au/courses/1/pages/a'), [])
        items = discover_recordings('<iframe src="https://echo360.net.au/ui/player/example?secureLinkAccessDataId=private"></iframe>'*2,'https://canvas.qut.edu.au/courses/1/pages/a')
        self.assertEqual(len(items),1)
        self.assertNotIn('private',str(items))
    def test_endpoint(self):
        self.assertTrue(is_transcript_response('https://echo360.net.au/api/ui/echoplayer/secure-link-access-datas/x/medias/y/transcript'))
        self.assertFalse(is_transcript_response('https://evil.invalid/transcript'))
        self.assertFalse(is_transcript_response('https://echo360.net.au/video.mp4'))
    def test_lesson_endpoint_and_syllabus(self):
        from qut_toolkit.echo import syllabus_recordings
        self.assertTrue(is_transcript_response('https://echo360.net.au/api/ui/echoplayer/lessons/x/medias/y/transcript'))
        payload={'status':'ok','data':[{'type':'SyllabusLessonType','lesson':{'lesson':{'id':'synthetic-lesson','displayName':'Week 1'},'medias':[{'id':'synthetic-media','title':'Lecture','isAvailable':True},{'id':'hidden','isAvailable':True,'isHiddenDueToCaptions':True}]}}]}
        rows=syllabus_recordings(payload)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['title'],'Lecture')
        self.assertEqual(rows[0]['lesson_id'],'synthetic-lesson')

    def test_delayed_library_readiness_and_timeout(self):
        from qut_toolkit.echo import wait_for_caption_readiness
        class Page:
            calls=0
            def wait_for_timeout(self, ms):
                self.calls+=1
                self.asserted_ms=ms
        page=Page()
        self.assertTrue(wait_for_caption_readiness(page,lambda: page.calls>=3,4))
        self.assertEqual(page.calls,3)
        self.assertEqual(page.asserted_ms,500)
        page=Page()
        self.assertFalse(wait_for_caption_readiness(page,lambda: False,2))
        self.assertEqual(page.calls,4)

    def test_library_slide_deck_is_not_a_caption_recording(self):
        from qut_toolkit.echo import syllabus_recordings
        payload={'status':'ok','data':[{'lesson':{'lesson':{'id':'synthetic-lesson'},'medias':[
            {'id':'video','mediaType':'Video','isAvailable':True},
            {'id':'audio','mediaType':'Audio','isAvailable':True},
            {'id':'slides','mediaType':'Presentation','isAvailable':True}]}}]}
        self.assertEqual([x['provider_id'] for x in syllabus_recordings(payload)],['video','audio'])

    def test_canvas_url(self):
        self.assertTrue(safe_canvas_url('https://canvas.qut.edu.au/courses/1/pages/a'))
        for url in ['https://evil.invalid/courses/1','http://canvas.qut.edu.au/courses/1','https://canvas.qut.edu.au.evil.invalid/courses/1']:
            self.assertFalse(safe_canvas_url(url))

if __name__ == '__main__': unittest.main()
