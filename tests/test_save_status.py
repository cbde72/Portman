import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from Gui.PortMan_V09 import MainWindow
from portman.repository_v09 import RepositoryV09


class SaveStatusTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / 'test.sqlite'
        self.repo = RepositoryV09(self.path, backups=False)
        # WAL allows readers to proceed while a writer holds an exclusive lock;
        # the busy path of update_save_status is only reachable with a blocking
        # journal, so deactivate WAL for this test class.
        self.repo.store.db.execute('PRAGMA journal_mode=DELETE')
        self.writer = sqlite3.connect(self.path, timeout=0)
        self.label = Mock()
        self.label.text.return_value = 'Datenbank beschäftigt · Status wird erneut geprüft …'
        self.window = SimpleNamespace(repository=self.repo, job_center=SimpleNamespace(records=[]),
                                      saved_status=self.label, _last_revision=self.repo.revision())

    def tearDown(self):
        self.writer.close()
        self.repo.close()
        self.folder.cleanup()

    def test_exclusive_writer_does_not_block_timer_and_commit_is_detected(self):
        before = self.window._last_revision
        self.writer.execute('BEGIN EXCLUSIVE')
        self.writer.execute('UPDATE v09_revision SET value=value+1 WHERE id=1')
        started = time.monotonic()
        MainWindow.update_save_status(self.window)
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(self.window._last_revision, before)
        self.label.setText.assert_called_with('Datenbank beschäftigt · Status wird erneut geprüft …')
        self.assertEqual(self.repo.db.execute('PRAGMA busy_timeout').fetchone()[0], 30000)
        self.writer.commit()
        MainWindow.update_save_status(self.window)
        self.assertEqual(self.window._last_revision, before + 1)
        self.assertTrue(self.label.setText.call_args.args[0].startswith('Gespeichert'))

    def test_rollback_clears_busy_status_without_claiming_a_save(self):
        self.writer.execute('BEGIN EXCLUSIVE')
        MainWindow.update_save_status(self.window)
        self.writer.rollback()
        MainWindow.update_save_status(self.window)
        self.label.setText.assert_called_with('Bereit · Keine ungespeicherten Datenänderungen')

    def test_running_job_skips_database_poll(self):
        self.window.job_center.records = [{'end': None}]
        self.window.repository = Mock()
        MainWindow.update_save_status(self.window)
        self.window.repository.poll_revision.assert_not_called()
        self.label.setText.assert_called_with('Verarbeitung läuft …')

    def test_other_database_errors_propagate_and_restore_timeout(self):
        self.repo.db.execute('DROP TABLE v09_revision')
        self.repo.db.commit()
        with self.assertRaisesRegex(sqlite3.OperationalError, 'no such table'):
            self.repo.poll_revision()
        self.assertEqual(self.repo.db.execute('PRAGMA busy_timeout').fetchone()[0], 30000)


if __name__ == '__main__':
    unittest.main()
