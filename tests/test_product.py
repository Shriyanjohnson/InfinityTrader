from pathlib import Path
import sqlite3
import tempfile
import unittest

from early_access import save_signup


class SignupTests(unittest.TestCase):
    def test_signup_is_persisted_normalized_and_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "signups.sqlite3"
            save_signup(" User@example.com ", True, database)
            save_signup("user@example.com", True, database)
            with sqlite3.connect(database) as connection:
                rows = connection.execute("SELECT email, consent, created_at FROM signups").fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0][:2], ("user@example.com", 1))
            self.assertTrue(rows[0][2])
            self.assertEqual(database.stat().st_mode & 0o777, 0o600)

    def test_invalid_email_and_missing_consent_never_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "signups.sqlite3"
            for email, consent in [("not-an-email", True), ("u@example.com", False)]:
                with self.subTest(email=email), self.assertRaises(ValueError):
                    save_signup(email, consent, database)
            self.assertFalse(database.exists())
