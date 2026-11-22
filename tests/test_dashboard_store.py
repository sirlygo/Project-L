import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_store import (
    add_staff_note, create_ticket_record, list_appeals, list_cases, list_staff_notes,
    list_tickets, overview,
    record_case, record_staff_response, review_appeal, submit_appeal, update_ticket,
    get_transcript, save_transcript, search_transcripts,
)


class DashboardStoreTests(unittest.TestCase):
    def test_cases_tickets_appeals_and_overview(self):
        with tempfile.TemporaryDirectory() as directory, patch(
            "dashboard_store.DB_PATH", Path(directory) / "dashboard.db",
        ):
            case_id = record_case(1, 2, 3, "warn", "Be respectful")
            self.assertEqual(list_cases(1)[0]["id"], case_id)
            self.assertEqual(list_cases(1, member_id=2)[0]["action"], "warn")
            self.assertEqual(list_cases(2), [])
            note_id = add_staff_note(1, "case", case_id, 3, "Internal context")
            self.assertEqual(list_staff_notes(1, "case", case_id)[0]["id"], note_id)
            self.assertEqual(list_staff_notes(2, "case", case_id), [])

            create_ticket_record(10, 1, 2, "help", {"Issue": "Can’t join"})
            self.assertEqual(list_tickets(1)[0]["answers"]["Issue"], "Can’t join")
            self.assertTrue(update_ticket(10, 1, priority="high", assignee_id=3))
            self.assertTrue(update_ticket(10, 1, status="closed"))
            self.assertEqual(list_tickets(1, status="closed")[0]["priority"], "high")
            self.assertTrue(record_staff_response(10, 1))
            self.assertFalse(record_staff_response(10, 1))
            self.assertIsNotNone(list_tickets(1)[0]["first_staff_response_at"])

            appeal_id = submit_appeal(1, 2, "Please reconsider", case_id)
            self.assertEqual(list_appeals(1, status="open")[0]["id"], appeal_id)
            self.assertTrue(review_appeal(1, appeal_id, 3, "approved", "Okay"))
            self.assertFalse(review_appeal(1, appeal_id, 3, "denied", "No"))
            self.assertEqual(overview(1), {
                "cases": 1, "tickets": 1, "appeals": 1,
                "open_tickets": 0, "open_appeals": 0,
                "avg_first_response_seconds": 0,
                "cases_last_7_days": 1, "tickets_last_7_days": 1,
            })
            save_transcript(1, 10, "The member needs help joining voice chat.")
            self.assertEqual(len(search_transcripts(1, "voice chat")), 1)
            self.assertEqual(search_transcripts(2, "voice chat"), [])
            self.assertIn("needs help", get_transcript(1, 10))


if __name__ == "__main__":
    unittest.main()
