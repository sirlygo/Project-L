import unittest

from live_smoke_test import has_bot_panel, message_component_ids, missing_panel_names


def message(author_id, *custom_ids):
    return {
        "author": {"id": str(author_id)},
        "components": [
            {
                "type": 1,
                "components": [
                    {"type": 2, "custom_id": custom_id} for custom_id in custom_ids
                ],
            }
        ],
    }


class LiveSmokePanelTests(unittest.TestCase):
    def test_component_ids_are_extracted_from_raw_messages(self):
        self.assertEqual(
            message_component_ids(message(5, "one", "two")), {"one", "two"}
        )

    def test_all_standard_panels_are_detected(self):
        messages = [
            message(7, "voicechannel"),
            message(7, "publicvoicecreate"),
            message(7, "ticket_help", "ticket_suggestions", "ticket_report"),
        ]
        self.assertEqual(
            missing_panel_names(
                messages,
                bot_user_id=7,
                reaction_roles_configured=False,
            ),
            [],
        )

    def test_other_authors_and_missing_reaction_panel_are_rejected(self):
        messages = [
            message(99, "verify"),
            message(7, "voicechannel"),
            message(7, "publicvoicecreate"),
            message(7, "ticket_help", "ticket_suggestions", "ticket_report"),
        ]
        missing = missing_panel_names(
            messages,
            bot_user_id=7,
            reaction_roles_configured=True,
        )
        self.assertEqual(missing, ["reaction roles"])

    def test_verify_panel_is_checked_in_the_correct_channel(self):
        self.assertTrue(
            has_bot_panel([message(7, "verify")], bot_user_id=7, required=frozenset({"verify"}))
        )
        self.assertFalse(
            has_bot_panel([message(99, "verify")], bot_user_id=7, required=frozenset({"verify"}))
        )


if __name__ == "__main__":
    unittest.main()
