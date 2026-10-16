"""Synthetic standalone CLI acceptance; never opens a real browser."""
from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import qut_sync
from test_sync import FixtureClient


class CLITests(unittest.TestCase):
    def run_cli(self,args):
        out=io.StringIO();err=io.StringIO()
        with redirect_stdout(out),redirect_stderr(err): code=qut_sync.main(args)
        return code,out.getvalue(),err.getvalue()

    def test_help_all_commands_subprocess(self):
        script=Path(qut_sync.__file__)
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        for command in ([],['setup'],['courses'],['sync'],['report']):
            result=subprocess.run([sys.executable,str(script),*command,'--help'],capture_output=True,text=True,env=env)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('--cdp-url',result.stdout)

    def test_setup_nonsecret_then_sync_report_and_close(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'library';cfg=Path(d)/'config.json'
            code,out,err=self.run_cli(['setup','--root',str(root),'--config',str(cfg),'--cookie-cache',str(Path(d)/'private-cache')])
            self.assertEqual(code,0,err)
            data=json.loads(cfg.read_text())
            self.assertEqual(set(data),{'root','timezone'})
            self.assertFalse((root/'.obsidian').exists())
            c=FixtureClient();c.close=lambda: setattr(c,'closed',True)
            with patch.object(qut_sync.CanvasClient,'from_config',return_value=c):
                code,out,err=self.run_cli(['--config',str(cfg),'sync','7'])
            self.assertEqual(code,0,err)
            self.assertTrue(c.closed)
            self.assertTrue(json.loads(out)['complete'])
            code,out,err=self.run_cli(['report','--config',str(cfg),'--json'])
            self.assertEqual(code,0,err)
            self.assertEqual(len(json.loads(out)['courses']),1)

    def test_auth_failure_replaces_previous_clean_report(self):
        from qut_toolkit.client import CanvasError
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'config.json';root=Path(d)/'library'
            self.run_cli(['setup','--config',str(cfg),'--root',str(root)])
            with patch.object(qut_sync.CanvasClient,'from_config',side_effect=CanvasError('auth','PRIVATE synthetic token')):
                code,out,err=self.run_cli(['sync','7','--config',str(cfg)])
            self.assertEqual(code,1)
            self.assertNotIn('PRIVATE',err)
            data=json.loads((root/'reports/latest-sync.json').read_text())
            self.assertFalse(data['complete'])
            self.assertTrue(data['errors'])

    def test_cdp_factory_and_empty_all_report_not_clean(self):
        with tempfile.TemporaryDirectory() as d:
            cfg=Path(d)/'config.json';root=Path(d)/'library'
            self.run_cli(['setup','--config',str(cfg),'--root',str(root)])
            class Empty:
                closed=False
                def list(self,path): return []
                def close(self): self.closed=True
            client=Empty()
            with patch.object(qut_sync.CanvasClient,'from_cdp',return_value=client,create=True) as factory:
                code,out,err=self.run_cli(['sync','--all','--config',str(cfg),'--cdp-url','http://localhost:9222'])
            self.assertEqual(code,1)
            self.assertTrue(client.closed)
            factory.assert_called_once()
            self.assertEqual(factory.call_args.args[1],'http://localhost:9222')
            self.assertFalse(json.loads(out)['complete'])

if __name__=='__main__': unittest.main()
