import unittest

from memory.short_term_memory import ConversationMemory


class ConversationMemoryTests(unittest.TestCase):
    def test_keeps_only_newest_messages(self):
        memory = ConversationMemory(max_messages=2)
        memory.add("user", "one")
        memory.add("assistant", "two")
        memory.add("user", "three")
        self.assertEqual([item.content for item in memory.recent()], ["two", "three"])

    def test_context_is_bounded_and_ordered(self):
        memory = ConversationMemory(max_context_chars=25)
        memory.add("user", "first message")
        memory.add("assistant", "second message")
        context = memory.build_context()
        self.assertLessEqual(len(context), 25)
        self.assertIn("AI: second message", context)

    def test_clear_forgets_messages(self):
        memory = ConversationMemory()
        memory.add("user", "remember this")
        memory.clear()
        self.assertEqual(memory.recent(), [])


if __name__ == "__main__":
    unittest.main()
