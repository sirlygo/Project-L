import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from ticket_forms import DEFAULT_FORMS, TicketOpenModal, validate_forms


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


class TicketModalIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_modal_uses_interaction_server_configuration(self):
        guild = SimpleNamespace(id=2, get_channel=lambda _id: None)
        interaction = SimpleNamespace(guild=guild, response=SimpleNamespace(send_message=AsyncMock()))
        modal = TicketOpenModal("help", [])
        with patch("ticket_forms.load_active_guild_config", return_value={"guildId": 2, "tickets": {"category_help": 22}}) as load:
            await modal.on_submit(interaction)
        load.assert_called_once_with(2)
        interaction.response.send_message.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
