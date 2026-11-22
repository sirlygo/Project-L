import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_store import (
    add_staff_note, cancel_announcement, claim_due_announcements,
    create_ticket_record, finish_announcement, get_appeal, get_config_snapshot, get_ticket,
    list_announcements, list_appeals, list_cases, list_staff_notes,
    list_tickets, overview,
    mark_interrupted_announcements_failed, mark_response_alerted, overdue_tickets,
    purge_transcripts, record_case,
    record_config_snapshot, schedule_announcement,
    record_staff_response, review_appeal, submit_appeal, update_ticket,
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
            snapshot_id = record_config_snapshot(1, 3, {"branding": {"rulesText": "old"}})
            self.assertEqual(get_config_snapshot(1, snapshot_id)["branding"]["rulesText"], "old")
            self.assertIsNone(get_config_snapshot(2, snapshot_id))
            due = int(time.time()) + 3600
            scheduled = schedule_announcement(1, 10, 3, "Movie night Friday", due)
            self.assertEqual(list_announcements(2), [])
            self.assertEqual(claim_due_announcements(1, now=due - 1), [])
            self.assertEqual(claim_due_announcements(1, now=due)[0]["id"], scheduled)
            self.assertEqual(claim_due_announcements(1, now=due), [])
            self.assertEqual(mark_interrupted_announcements_failed(2), 0)
            self.assertEqual(mark_interrupted_announcements_failed(1), 1)
            self.assertEqual(list_announcements(1)[0]["status"], "failed")
            finish_announcement(1, scheduled, True)
            self.assertEqual(list_announcements(1)[0]["status"], "failed")
            self.assertFalse(cancel_announcement(1, scheduled))
            note_id = add_staff_note(1, "case", case_id, 3, "Internal context")
            self.assertEqual(list_staff_notes(1, "case", case_id)[0]["id"], note_id)
            self.assertEqual(list_staff_notes(2, "case", case_id), [])

            create_ticket_record(10, 1, 2, "help", {"Issue": "Can’t join"})
            self.assertEqual(get_ticket(1, 10)["owner_id"], 2)
            self.assertIsNone(get_ticket(2, 10))
            self.assertEqual(len(overdue_tickets(1, 1, now=9999999999)), 1)
            self.assertTrue(mark_response_alerted(1, 10))
            self.assertEqual(overdue_tickets(1, 1, now=9999999999), [])
            self.assertEqual(list_tickets(1)[0]["answers"]["Issue"], "Can’t join")
            self.assertTrue(update_ticket(10, 1, priority="high", assignee_id=3))
            self.assertTrue(update_ticket(10, 1, status="closed"))
            self.assertEqual(list_tickets(1, status="closed")[0]["priority"], "high")
            self.assertTrue(record_staff_response(10, 1))
            self.assertFalse(record_staff_response(10, 1))
            self.assertIsNotNone(list_tickets(1)[0]["first_staff_response_at"])

            appeal_id = submit_appeal(1, 2, "Please reconsider", case_id)
            self.assertEqual(get_appeal(1, appeal_id)["member_id"], 2)
            self.assertIsNone(get_appeal(2, appeal_id))
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
            self.assertEqual(purge_transcripts(1, 9999999999), 1)
            self.assertIsNone(get_transcript(1, 10))


if __name__ == "__main__":
    unittest.main()
