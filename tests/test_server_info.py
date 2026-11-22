import unittest

from Commands.server_info import answer_question


class ServerInfoTests(unittest.TestCase):
    def test_known_questions_have_answers(self):
        self.assertIn("verification", answer_question("tell me about project L", 123, 0))
        self.assertIn("client_id=123", answer_question("how can I get this in my server", 123, 0))

    def test_unrelated_mention_gets_no_answer(self):
        self.assertIsNone(answer_question("hello", 123, 0))
