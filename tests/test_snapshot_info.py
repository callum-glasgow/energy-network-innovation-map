import unittest
from scripts.snapshot_info import describe, summary


class SnapshotTests(unittest.TestCase):
    def test_import_time_and_build_time_do_not_replace_unknown_source_checks(self):
        data=describe([{'owner':'Network A','imported_at':'2026-10-11T10:00:00Z'},
                       {'owner':'Network B','source_checked_at':'2026-10-07T10:00:00Z'}],
                      '2026-10-12T10:00:00Z')
        self.assertEqual(data['dates']['source_checked_at']['missing'],1)
        self.assertEqual(data['dates']['source_checked_at']['latest'],'2026-10-07T10:00:00Z')
        self.assertEqual(data['owners'],{'Network A':1,'Network B':1})
        self.assertIn('Build time is not a fresh ENA check',summary(data))
