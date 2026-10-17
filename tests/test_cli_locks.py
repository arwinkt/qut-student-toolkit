from pathlib import Path
import subprocess,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from qut_toolkit.locking import writer_lock
ROOT=Path(__file__).resolve().parents[1]

class CLILockTests(unittest.TestCase):
    def test_public_writers_refuse_contention_before_checkpoint_changes(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d).resolve();library=base/'library';source=base/'source';source.mkdir();(source/'a.txt').write_text('synthetic')
            with writer_lock(library):
                checkpoint=library/'reports/latest-sync.json';checkpoint.parent.mkdir();checkpoint.write_text('synthetic checkpoint')
                commands=[(['qut_sync.py','sync','7','--root',str(library)],1),
                          (['qut_transcripts.py','--course-id','7','--root',str(library)],2),
                          (['scan_school.py','--source',str(source),'--output',str(library)],2)]
                for args,code in commands:
                    result=subprocess.run([sys.executable,str(ROOT/'scripts'/args[0]),*args[1:]],capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,code,result.stdout+result.stderr)
                    self.assertIn('busy',result.stderr.lower())
                    self.assertEqual(checkpoint.read_text(),'synthetic checkpoint')
                self.assertFalse((library/'units').exists())
