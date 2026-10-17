"""Caption discovery regressions using synthetic clients only."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from qut_toolkit.client import CanvasError
from qut_toolkit.recording_sync import course_sources


class DiscoveryClient:
    base_url = 'https://canvas.qut.edu.au'

    def __init__(self):
        self.calls = []

    def list(self, path):
        self.calls.append(path)
        if '/pages?' in path or '/external_tools?' in path:
            return []
        if '/modules?' in path:
            return [{'id': 1}, {'id': 2}]
        if '/modules/1/items?' in path:
            raise CanvasError('http', 'denied?token=EXCEPTION_SECRET#FRAGMENT_SECRET', 403)
        if '/modules/2/items?' in path:
            return [{'type': 'Page', 'page_url': 'lecture', 'title': 'Lecture'}]
        raise AssertionError(path)

    def get(self, path):
        self.calls.append(path)
        return {'title': 'Lecture', 'body': '<iframe src="https://echo360.net.au/ui/player/synthetic"></iframe>'}


class RecordingDiscoveryRegressions(unittest.TestCase):
    def assert_safe_error(self, error, stage):
        self.assertEqual(error['stage'], stage)
        self.assertEqual(error['kind'], 'http')
        if 'module_id' in error or stage == 'page':
            self.assertEqual(error['status'], 403)
        self.assertEqual(error['message'], 'Recording discovery failed; coverage is incomplete')
        serialized = json.dumps(error)
        for secret in ('EXCEPTION_SECRET', 'FRAGMENT_SECRET', 'PASSWORD_SECRET', 'QUERY_SECRET'):
            self.assertNotIn(secret, serialized)

    def test_denied_module_does_not_hide_later_module_echo_page(self):
        client = DiscoveryClient()
        sources, errors = course_sources(client, 7)
        self.assertEqual([s['source_url'] for s in sources],
                         ['https://canvas.qut.edu.au/courses/7/pages/lecture'])
        self.assertEqual(sources[0]['kinds'], ['echo360'])
        self.assertIn('/api/v1/courses/7/modules/2/items?per_page=100', client.calls)
        self.assertEqual(len(errors), 1)
        self.assert_safe_error(errors[0], 'modules')
        self.assertEqual(errors[0]['module_id'], '1')

    def test_each_denied_module_retains_its_own_identifier(self):
        class DeniedModules(DiscoveryClient):
            def list(self, path):
                if '/items?' in path:
                    raise CanvasError('http', 'EXCEPTION_SECRET', 403)
                return super().list(path)

        sources, errors = course_sources(DeniedModules(), 7)
        self.assertEqual(sources, [])
        self.assertEqual([e.get('module_id') for e in errors], ['1', '2'])
        for error in errors:
            self.assert_safe_error(error, 'modules')

    def test_module_listing_failure_still_checks_pages(self):
        class DeniedListing(DiscoveryClient):
            def list(self, path):
                if '/modules?' in path:
                    raise CanvasError('http', 'EXCEPTION_SECRET', 403)
                if '/pages?' in path:
                    return [{'url': 'lecture'}]
                return super().list(path)

        sources, errors = course_sources(DeniedListing(), 7)
        self.assertEqual(len(sources), 1)
        self.assertEqual(len(errors), 1)
        self.assert_safe_error(errors[0], 'modules')
        self.assertNotIn('module_id', errors[0])

    def test_failed_pages_retain_distinct_safe_source_references(self):
        class DeniedPages(DiscoveryClient):
            def list(self, path):
                if '/pages?' in path:
                    return [{'url': 'first-lecture'}, {'url': 'second-lecture'}]
                return []

            def get(self, path):
                raise CanvasError('http', 'denied?token=EXCEPTION_SECRET#FRAGMENT_SECRET', 403)

        sources, errors = course_sources(DeniedPages(), 7)
        self.assertEqual(sources, [])
        self.assertEqual([e.get('source_url') for e in errors], [
            'https://canvas.qut.edu.au/courses/7/pages/first-lecture',
            'https://canvas.qut.edu.au/courses/7/pages/second-lecture',
        ])
        for error in errors:
            self.assert_safe_error(error, 'page')

    def test_page_error_reference_strips_queries_and_rejects_credentials(self):
        class DeniedPage(DiscoveryClient):
            def list(self, path):
                return [{'url': 'lecture'}] if '/pages?' in path else []

            def get(self, path):
                raise CanvasError('http', 'EXCEPTION_SECRET', 403)

        for base_url, expected in (
            ('https://canvas.qut.edu.au?token=QUERY_SECRET#FRAGMENT_SECRET', 'https://canvas.qut.edu.au'),
            ('https://user:PASSWORD_SECRET@canvas.qut.edu.au', ''),
        ):
            with self.subTest(base_url_kind='credentials' if '@' in base_url else 'query'):
                client = DeniedPage()
                client.base_url = base_url
                sources, errors = course_sources(client, 7)
                self.assertEqual(sources, [])
                self.assertEqual(len(errors), 1)
                self.assert_safe_error(errors[0], 'page')
                self.assertEqual(errors[0].get('source_url'), expected)


if __name__ == '__main__':
    unittest.main()
