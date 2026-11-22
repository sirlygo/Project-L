import unittest

from ticket_forms import DEFAULT_FORMS, validate_forms


class TicketFormTests(unittest.TestCase):
    def test_defaults_and_custom_questions(self):
        self.assertEqual(validate_forms({})["help"], DEFAULT_FORMS["help"])
        forms = validate_forms({"help": [{"label": "Order number", "required": False, "maxLength": 50}]})
        self.assertEqual(forms["help"][0]["label"], "Order number")
        self.assertFalse(forms["help"][0]["required"])

    def test_question_limits(self):
        with self.assertRaises(ValueError):
            validate_forms({"help": [{"label": "x"}] * 6})
        with self.assertRaises(ValueError):
            validate_forms({"help": [{"label": "x" * 46}]})


if __name__ == "__main__":
    unittest.main()
