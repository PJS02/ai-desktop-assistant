import unittest

from memory.long_term_memory import get_importance_score


class ImportanceScoreTests(unittest.TestCase):
    def test_reads_valid_importance_score(self):
        self.assertEqual(get_importance_score('{"text": "기억해", "importance": 8}'), 8)

    def test_rejects_invalid_or_out_of_range_score(self):
        self.assertEqual(get_importance_score('{"importance": 11}'), 0)
        self.assertEqual(get_importance_score("not json"), 0)
        for response in ('{"importance": true}', '{"importance": 7.9}', '{"importance": "8"}', '[]'):
            self.assertEqual(get_importance_score(response), 0)
