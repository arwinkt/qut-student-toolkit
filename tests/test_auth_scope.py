import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('canvas_auth', Path(__file__).parents[1] / 'scripts' / 'canvas_auth.py')
auth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(auth)

class CookieScopeTests(unittest.TestCase):
    def test_filters_other_domains_and_non_api_paths(self):
        cookies = [
            {'name': 'canvas', 'value': 'synthetic-only', 'domain': 'canvas.qut.edu.au', 'path': '/'},
            {'name': 'parent', 'value': 'synthetic-only', 'domain': '.qut.edu.au', 'path': '/'},
            {'name': 'outlook', 'value': 'not-for-canvas', 'domain': 'outlook.office.com', 'path': '/'},
            {'name': 'evil', 'value': 'not-for-canvas', 'domain': 'canvas.qut.edu.au.evil.test', 'path': '/'},
            {'name': 'other', 'value': 'not-for-api', 'domain': 'canvas.qut.edu.au', 'path': '/other'},
        ]
        selected = auth.canvas_api_cookies(cookies)
        self.assertEqual([c['name'] for c in selected], ['canvas', 'parent'])

    def test_empty_does_not_fallback_to_all_cookies(self):
        self.assertEqual(auth.canvas_api_cookies([{'name':'x','value':'synthetic','domain':'example.test','path':'/'}]), [])

    def test_parent_suffix_boundary(self):
        self.assertEqual(auth.canvas_api_cookies([{'name':'x','value':'synthetic','domain':'.ut.edu.au','path':'/'}]), [])

if __name__ == '__main__':
    unittest.main()
