import unittest

from moderation_policy import escalation_for_warning_count, validate_escalation


class ModerationPolicyTests(unittest.TestCase):
    def test_exact_threshold_only(self):
        steps = [{"count": 5, "action": "timeout", "minutes": 60}]
        self.assertIsNone(escalation_for_warning_count(steps, 4))
        self.assertEqual(escalation_for_warning_count(steps, 5)["minutes"], 60)
        self.assertIsNone(escalation_for_warning_count(steps, 6))

    def test_invalid_or_duplicate_steps_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_escalation([{"count": 2, "action": "timeout", "minutes": 0}])
        with self.assertRaises(ValueError):
            validate_escalation([
                {"count": 2, "action": "ban"}, {"count": 2, "action": "ban"},
            ])
