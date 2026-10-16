"""Synthetic caption fixtures only. Never load a real student recording in tests."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from qut_toolkit.transcripts import parse_vtt, parse_srt, parse_echo, export_transcript, Cue, CaptionError


class TranscriptTests(unittest.TestCase):
    def test_vtt_multiline_speakers_and_settings(self):
        text = '\ufeffWEBVTT\n\nNOTE synthetic\nignore this\n\nid\n00:00:01.000 --> 00:00:02.500 align:start\n<v Teacher>Hello &amp; welcome</v>\nsecond line\n\n00:03.000 --> 00:04.000\nLast words\n'
        cues = parse_vtt(text)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0], Cue(1000, 2500, 'Hello & welcome\nsecond line', 'Teacher'))
        self.assertEqual(cues[-1].text, 'Last words')

    def test_vtt_header_metadata(self):
        cues=parse_vtt('WEBVTT\nKind: captions\nLanguage: en\n\n00:00:01.000 --> 00:00:02.000\nSynthetic\n')
        self.assertEqual(cues[0].text,'Synthetic')

    def test_srt(self):
        cues = parse_srt('1\n00:00:01,200 --> 00:00:02,300\nSynthetic\n\n2\n00:00:03,000 --> 00:00:04,000\nLast\n')
        self.assertEqual(cues[0].start_ms, 1200)
        self.assertEqual(len(cues), 2)

    def test_malformed_rejected_not_partially_exported(self):
        for text in ['WEBVTT\n\n00:61.000 --> 00:62.000\nbad', 'WEBVTT\n\n00:03.000 --> 00:02.000\nbad', 'WEBVTT\n\nnot a cue', 'WEBVTT', '<html>login</html>']:
            with self.subTest(text=text), self.assertRaises(CaptionError):
                parse_vtt(text)
        with self.assertRaises(CaptionError):
            parse_echo({'status':'ok','data':{'contentJSON':{'cues':[{'startMs':True,'endMs':4,'content':'bad'}]}}})

    def test_echo_automation_and_unknown_language(self):
        payload = {'status':'ok','data':{'status':'Available','isAutomated':True,'mediaId':'synthetic-id','contentJSON':{'cues':[{'startMs':0,'endMs':1000,'content':'First','speaker':'Speaker 0'},{'startMs':1000,'endMs':2000,'content':'Last'}]}}}
        cues, metadata = parse_echo(payload)
        self.assertEqual(len(cues), 2)
        self.assertEqual(metadata['caption_type'], 'automatic')
        self.assertIsNone(metadata['language'])
        self.assertEqual(cues[-1].text, 'Last')
        with self.assertRaises(CaptionError):
            parse_echo({'status':'ok','data':{'status':'Processing','contentJSON':{'cues':[]}}})

    def test_export_incremental_and_local_edit(self):
        cues = [Cue(0,1000,'First','Teacher'), Cue(1000,2000,'Last')]
        with tempfile.TemporaryDirectory() as d:
            result = export_transcript(d,'https://canvas.qut.edu.au/courses/1/pages/a','Synthetic',cues,{'provider':'echo360','provider_id':'synthetic','caption_type':'automatic'})
            path = Path(result['directory'])
            self.assertEqual(result['cue_count'],2)
            self.assertIn('Last', (path/'transcript.md').read_text())
            self.assertEqual(len(parse_vtt((path/'captions.vtt').read_text())),2)
            second = export_transcript(d,'https://canvas.qut.edu.au/courses/1/pages/a','Synthetic',cues,{'provider':'echo360','provider_id':'synthetic','caption_type':'automatic'})
            self.assertNotIn('updated', second['counts'])
            (path/'transcript.md').write_text('personal annotations')
            cues[0] = Cue(0,1000,'Changed upstream')
            third = export_transcript(d,'https://canvas.qut.edu.au/courses/1/pages/a','Synthetic',cues,{'provider':'echo360','provider_id':'synthetic'})
            self.assertEqual((path/'transcript.md').read_text(),'personal annotations')
            self.assertIn('conflict', third['counts'])
            self.assertEqual(len(list(Path(d).glob('lecture-*'))),1)

    def test_secret_urls_cannot_be_exported(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            export_transcript(d,'https://evil.test/?token=secret','X',[Cue(0,1,'a')],{})

if __name__=='__main__': unittest.main()
