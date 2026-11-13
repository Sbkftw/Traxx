import csv
import io
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from traxx_core.app import parse_args
from traxx_core.downloading import workflow as w
from traxx_core.downloading.metadata import MetadataResult


class BatchDownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.options = w.DownloadOptions(root / 'tracks.csv', str(root / 'downloads'), 'Playlist', 'mp3', False, 2, False, '', '')
        self.rows = [dict(track_name=f'Track {i}', artists='Artist', downloaded='yes' if i == 0 else 'no') for i in range(6)]
        for name, value in [('detect_cookie_browser_candidates', []), ('build_js_runtimes', []), ('tag_downloaded_file', MetadataResult(True))]:
            mock = patch.object(w, name, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.selection = patch.object(w, 'pick_best_candidate', return_value=({'id': 'video', 'title': 'Title'}, 'match')).start()
        self.addCleanup(patch.stopall)
        self.download = patch.object(w, 'run_with_auth_fallback', return_value=subprocess.CompletedProcess([], 0, '', '')).start()

    def run_batch(self, rows=None, **options):
        with redirect_stdout(io.StringIO()):
            w.download_tracks(self.rows if rows is None else rows, replace(self.options, **options))

    def saved_rows(self):
        with self.options.csv_path.open(newline='', encoding='utf-8') as file:
            return list(csv.DictReader(file))

    def test_resume_from_saved_csv(self):
        self.run_batch()
        saved = self.saved_rows()
        self.assertEqual([r['downloaded'] for r in saved], ['yes'] * 3 + ['no'] * 3)
        self.assertEqual(self.download.call_count, 2)
        self.run_batch(saved)
        self.assertEqual([r['downloaded'] for r in self.saved_rows()], ['yes'] * 5 + ['no'])
        self.assertEqual(self.download.call_count, 4)

    def test_failed_download_does_not_use_quota(self):
        self.download.side_effect = [subprocess.CompletedProcess([], 1, '', 'download failed'), subprocess.CompletedProcess([], 0, '', ''), subprocess.CompletedProcess([], 0, '', '')]
        self.run_batch()
        self.assertEqual(self.download.call_count, 3)
        self.assertEqual([r['downloaded'] for r in self.saved_rows()], ['yes', 'no', 'yes', 'yes', 'no', 'no'])

    def test_failed_match_does_not_use_quota(self):
        self.selection.side_effect = lambda row, *args: (None, 'no match') if row['track_name'] == 'Track 1' else ({'id': 'video', 'title': 'Title'}, 'match')
        self.run_batch()
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(self.saved_rows()[1]['downloaded'], 'no')
        self.assertEqual(self.saved_rows()[3]['downloaded'], 'yes')

    def test_dry_run_limits_previews_without_changing_status(self):
        with patch.object(w, 'run_ytdlp_command') as preview:
            self.run_batch(dry_run=True)
        self.assertEqual(preview.call_count, 2)
        self.download.assert_not_called()
        self.assertFalse(self.options.csv_path.exists())
        self.assertEqual(sum(r['downloaded'] == 'yes' for r in self.rows), 1)

    def test_fewer_pending_tracks_than_limit(self):
        self.run_batch(limit=300)
        self.assertEqual(self.download.call_count, 5)
        self.assertTrue(all(r['downloaded'] == 'yes' for r in self.saved_rows()))

    def test_cli_limit_validation(self):
        for value in ['0', '-1', 'abc']:
            with self.subTest(value=value), patch.object(sys, 'argv', ['traxx', '--limit', value]), redirect_stdout(io.StringIO()), patch('sys.stderr', new_callable=io.StringIO):
                with self.assertRaises(SystemExit) as error:
                    parse_args()
                self.assertEqual(error.exception.code, 2)
        with patch.object(sys, 'argv', ['traxx', '--limit', '300']):
            self.assertEqual(parse_args().limit, 300)
        with patch.object(sys, 'argv', ['traxx']):
            self.assertIsNone(parse_args().limit)


if __name__ == '__main__':
    unittest.main()
