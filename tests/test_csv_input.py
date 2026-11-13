import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from traxx_core import app


class CsvInputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'My playlist.csv'
        self.path.write_text('track_name,artists,downloaded\nTitle,Artist,no\nOld,Artist,yes\n', encoding='utf-8-sig')

    def test_csv_skips_spotify_and_passes_options(self):
        with patch.object(sys, 'argv', ['traxx', '--csv', str(self.path), '--limit', '300']), patch.object(app, 'load_dotenv'), patch.object(app, 'load_spotify_credentials') as credentials, patch.object(app, 'get_user_access_token') as oauth, patch.object(app, 'run_download_stage') as stage, redirect_stdout(io.StringIO()):
            app.main()
        credentials.assert_not_called()
        oauth.assert_not_called()
        rows, filename, name, args = stage.call_args.args
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['downloaded'], 'yes')
        self.assertEqual(filename, str(self.path))
        self.assertEqual(name, 'My playlist')
        self.assertEqual(args.limit, 300)

    def test_invalid_inputs(self):
        for extra in [['--no-download'], ['playlist-id'], ['--playlist-url', 'playlist-id']]:
            with self.subTest(extra=extra), patch.object(sys, 'argv', ['traxx', '--csv', str(self.path), *extra]), patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
                app.parse_args()
        with patch.object(sys, 'argv', ['traxx', '--csv', str(self.path.parent / 'missing.csv')]), patch('sys.stderr', new_callable=io.StringIO), self.assertRaises(SystemExit):
            app.parse_args()

    def test_invalid_csv_is_not_modified(self):
        for content in ['name,artists\nTitle,Artist\n', 'track_name,artists\nTitle,Artist,extra\n', 'track_name,artists\nTitle\n']:
            self.path.write_text(content, encoding='utf-8')
            with self.subTest(content=content), self.assertRaises(ValueError):
                app.download_from_csv(self.path, None)
            self.assertEqual(self.path.read_text(encoding='utf-8'), content)

    def test_empty_csv_skips_download(self):
        self.path.write_text('track_name,artists\n', encoding='utf-8')
        with patch.object(app, 'run_download_stage') as stage, redirect_stdout(io.StringIO()):
            app.download_from_csv(self.path, None)
        stage.assert_not_called()

    def test_dry_run_preserves_csv_without_status_column(self):
        self.path.write_text('track_name,artists\nTitle,Artist\n', encoding='utf-8')
        original = self.path.read_bytes()
        with patch.object(sys, 'argv', ['traxx', '--csv', str(self.path), '--dry-run']), patch.object(app, 'ensure_ytdlp_installed'), patch.object(app, 'preflight_ytdlp_runtime_check'), patch.object(app, 'has_ffmpeg', return_value=False), redirect_stdout(io.StringIO()):
            app.download_from_csv(self.path, app.parse_args())
        self.assertEqual(self.path.read_bytes(), original)

    def test_success_updates_input_csv(self):
        from subprocess import CompletedProcess
        from traxx_core.downloading import workflow
        from traxx_core.downloading.metadata import MetadataResult
        with patch.object(sys, 'argv', ['traxx', '--csv', str(self.path), '--limit', '1']), patch.object(app, 'load_dotenv'), patch.object(app, 'ensure_ytdlp_installed'), patch.object(app, 'preflight_ytdlp_runtime_check'), patch.object(app, 'has_ffmpeg', return_value=False), patch.object(workflow, 'build_js_runtimes', return_value=[]), patch.object(workflow, 'pick_best_candidate', return_value=({'id': 'video', 'title': 'Title'}, 'match')), patch.object(workflow, 'run_with_auth_fallback', return_value=CompletedProcess([], 0, '', '')), patch.object(workflow, 'tag_downloaded_file', return_value=MetadataResult(True)), redirect_stdout(io.StringIO()):
            app.main()
        with self.path.open(encoding='utf-8-sig', newline='') as file:
            rows = list(csv.DictReader(file))
        self.assertEqual([row['downloaded'] for row in rows], ['yes', 'yes'])


if __name__ == '__main__':
    unittest.main()
