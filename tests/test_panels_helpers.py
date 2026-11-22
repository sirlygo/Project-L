import unittest
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

from Commands.panels import (
    PANEL_ART_IMAGES,
    BuiltinSelfRoleView,
    ensure_automatic_panels,
    is_self_role_panel_message,
    normalized_panel_title,
    panel_kind_for_message,
    reaction_role_options,
    repair_managed_panel_art,
    repair_self_role_panel_images,
    send_panel_with_local_art,
    ticket_embed,
    verification_embed,
)
from self_roles import ROLE_GROUPS


class PanelHelperTests(unittest.TestCase):
    def test_decorated_self_role_titles_are_normalized(self):
        self.assertEqual(normalized_panel_title(" ** Game Roles** "), "game roles")

    def test_panel_match_requires_known_title_components_and_bot_author(self):
        message = SimpleNamespace(
            author=SimpleNamespace(id=10),
            embeds=[discord.Embed(title="**Color Roles**")],
            components=[object()],
        )
        self.assertTrue(is_self_role_panel_message(message, 10))
        self.assertFalse(is_self_role_panel_message(message, 11))
        message.components = []
        self.assertFalse(is_self_role_panel_message(message, 10))

    def test_new_self_role_panels_are_not_legacy_repair_targets(self):
        message = SimpleNamespace(
            author=SimpleNamespace(id=10),
            embeds=[discord.Embed(title="Color Roles")],
            components=[SimpleNamespace(children=[SimpleNamespace(custom_id="selfrole:colors:0")])],
        )
        self.assertFalse(is_self_role_panel_message(message, 10))

    def test_managed_panels_are_identified_by_stable_components(self):
        row = SimpleNamespace(
            children=[
                SimpleNamespace(custom_id="ticket_help"),
                SimpleNamespace(custom_id="ticket_suggestions"),
                SimpleNamespace(custom_id="ticket_report"),
            ]
        )
        message = SimpleNamespace(author=SimpleNamespace(id=10), components=[row])
        self.assertEqual(panel_kind_for_message(message, 10), "tickets")
        self.assertIsNone(panel_kind_for_message(message, 11))

    def test_standard_panel_embeds_have_no_external_image_dependencies(self):
        guild = SimpleNamespace(name="Example Server")
        for embed in (
            verification_embed(guild, discord.Colour.green()),
            ticket_embed(discord.Colour.green()),
        ):
            self.assertFalse(embed.image.url)
            self.assertNotIn("Lygo", str(embed.to_dict()))

    def test_default_everyone_role_is_never_offered_for_self_assignment(self):
        everyone = SimpleNamespace(
            id=7,
            name="@everyone",
            managed=False,
            is_default=lambda: True,
        )
        guild = SimpleNamespace(
            id=7,
            me=None,
            get_role=lambda _role_id: everyone,
        )
        self.assertEqual(reaction_role_options(guild, [7]), [])


class PanelRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_repair_uploads_a_same_message_attachment(self):
        edits = []

        async def edit(**kwargs):
            edits.append(kwargs)

        message = SimpleNamespace(
            id=123,
            author=SimpleNamespace(id=10),
            embeds=[discord.Embed(title="Gender Roles")],
            components=[object()],
            attachments=[],
            edit=edit,
        )

        class Channel:
            async def history(self, **_kwargs):
                yield message

        repaired, failures = await repair_self_role_panel_images(Channel(), 10)

        self.assertEqual(repaired, 1)
        self.assertEqual(failures, [])
        digest = sha256(PANEL_ART_IMAGES["self_roles:pronouns"].read_bytes()).hexdigest()[:10]
        filename = f"self_roles-pronouns-123-{digest}.gif"
        self.assertEqual(
            edits[0]["embed"].image.url,
            f"attachment://{filename}",
        )
        self.assertEqual(edits[0]["attachments"][0].filename, filename)

    async def test_repair_preserves_unrelated_attachments_and_components(self):
        unrelated = SimpleNamespace(filename="rules.pdf")
        components = [object(), object()]
        message = SimpleNamespace(
            id=456,
            author=SimpleNamespace(id=10),
            embeds=[discord.Embed(title="Platform Roles")],
            components=components,
            attachments=[unrelated],
            edit=AsyncMock(),
        )

        class Channel:
            async def history(self, **_kwargs):
                yield message

        repaired, failures = await repair_self_role_panel_images(Channel(), 10)

        self.assertEqual((repaired, failures), (1, []))
        sent = message.edit.await_args.kwargs
        self.assertIs(sent["attachments"][0], unrelated)
        digest = sha256(PANEL_ART_IMAGES["self_roles:platform"].read_bytes()).hexdigest()[:10]
        self.assertEqual(sent["attachments"][1].filename, f"self_roles-platform-456-{digest}.gif")
        self.assertIs(message.components, components)
        self.assertNotIn("view", sent)

    async def test_repair_is_idempotent_when_attachment_is_current(self):
        digest = sha256(PANEL_ART_IMAGES["self_roles:pings"].read_bytes()).hexdigest()[:10]
        filename = f"self_roles-pings-789-{digest}.gif"
        embed = discord.Embed(title="Server Notifications")
        embed.set_image(url=f"attachment://{filename}")
        message = SimpleNamespace(
            id=789,
            author=SimpleNamespace(id=10),
            embeds=[embed],
            components=[object()],
            attachments=[SimpleNamespace(filename=filename)],
            edit=AsyncMock(),
        )

        class Channel:
            async def history(self, **_kwargs):
                yield message

        repaired, failures = await repair_self_role_panel_images(Channel(), 10)

        self.assertEqual((repaired, failures), (0, []))
        message.edit.assert_not_awaited()


class AutomaticPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_roles_render_as_five_button_panels(self):
        from Commands.panels import send_managed_panel

        roles = {}
        next_id = 1000
        for group, choices in ROLE_GROUPS.items():
            roles[group] = {}
            for choice in choices:
                next_id += 1
                roles[group][choice] = next_id
        config = {"managedResources": {"selfRoles": roles}}
        guild = SimpleNamespace(get_role=lambda role_id: object() if role_id else None)
        view = BuiltinSelfRoleView(config, guild, "colors")
        self.assertEqual(len(view.children), len(ROLE_GROUPS["colors"]))
        self.assertEqual(view.children[0].custom_id, "selfrole:colors:0")
        sent = []

        class Channel:
            async def send(self, **kwargs):
                sent.append(kwargs)

        with patch("Commands.panels.load_config", return_value=config):
            for group in ROLE_GROUPS:
                await send_managed_panel(
                    f"self_roles:{group}", Channel(), guild, discord.Colour.green()
                )
        self.assertEqual(len(sent), 5)
        self.assertEqual(len(sent[-1]["view"].children), len(ROLE_GROUPS["pings"]))
        for group, message in zip(ROLE_GROUPS, sent):
            filename = message["file"].filename
            self.assertRegex(filename, rf"^project_l_self_roles_{group}_[0-9a-f]{{10}}\.gif$")
            self.assertEqual(message["file"].filename, filename)
            self.assertEqual(message["embed"].image.url, f"attachment://{filename}")

    async def test_self_roles_header_uses_original_banner_without_buttons(self):
        from Commands.panels import send_managed_panel

        sent = {}

        class Channel:
            async def send(self, **kwargs):
                sent.update(kwargs)

        await send_managed_panel("self_roles_header", Channel(), None, discord.Colour.green())
        self.assertEqual(sent["embed"].footer.text, "Project L • Self Roles Header")
        self.assertRegex(sent["file"].filename, r"^project_l_self_roles_header_[0-9a-f]{10}\.gif$")
        self.assertIsNone(sent["view"])

    async def test_self_roles_header_is_installed_before_group_art(self):
        class Channel:
            async def history(self, **_kwargs):
                if False:
                    yield None

        channel = Channel()
        guild = SimpleNamespace(get_channel=lambda _id: channel)
        client = SimpleNamespace(
            user=SimpleNamespace(id=42),
            colour=discord.Colour.green(),
            get_guild=lambda _id: guild,
            get_channel=lambda _id: None,
        )
        config = {
            "guildId": 7,
            "managedResources": {"panelsChannel": 99, "selfRoles": {"colors": {"Red": 123}}},
        }
        with (
            patch("Commands.panels.load_config", return_value=config),
            patch("Commands.panels.load_role_ids", return_value=[]),
            patch("Commands.panels.send_managed_panel", new_callable=AsyncMock),
        ):
            report = await ensure_automatic_panels(client)
        self.assertEqual(report.created[:6], ["self_roles_header", *(f"self_roles:{group}" for group in ROLE_GROUPS)])
    async def test_existing_text_only_panel_is_upgraded_in_place(self):
        message = SimpleNamespace(
            embeds=[discord.Embed(title="Verify")],
            attachments=[],
            edit=AsyncMock(),
        )
        with TemporaryDirectory() as temp_dir:
            art_path = Path(temp_dir) / "verification.png"
            art_path.write_bytes(b"test image contents")
            with patch.dict(
                "Commands.panels.PANEL_ART_IMAGES",
                {"verification": art_path},
                clear=False,
            ):
                updated = await repair_managed_panel_art(message, "verification")

        self.assertTrue(updated)
        message.edit.assert_awaited_once()
        edited = message.edit.await_args.kwargs
        self.assertEqual(
            edited["embed"].image.url,
            f"attachment://{edited['attachments'][-1].filename}",
        )
        self.assertRegex(
            edited["attachments"][-1].filename,
            r"^project_l_verification_[0-9a-f]{10}\.png$",
        )

    async def test_changed_self_role_gif_replaces_old_attachment(self):
        from Commands.panels import _managed_panel_art_filename

        with TemporaryDirectory() as temp_dir:
            art_path = Path(temp_dir) / "self_roles_colors.gif"
            art_path.write_bytes(b"animated version 1")
            with patch.dict("Commands.panels.PANEL_ART_IMAGES", {"self_roles:colors": art_path}):
                old_name = _managed_panel_art_filename("self_roles:colors")
                art_path.write_bytes(b"animated version 2")
                new_name = _managed_panel_art_filename("self_roles:colors")
                self.assertNotEqual(old_name, new_name)
                old_attachment = SimpleNamespace(filename=old_name)
                unrelated = SimpleNamespace(filename="keep_this.txt")
                embed = discord.Embed(title="Color Roles")
                embed.set_image(url=f"attachment://{old_name}")
                message = SimpleNamespace(
                    embeds=[embed],
                    attachments=[old_attachment, unrelated],
                    edit=AsyncMock(),
                )
                updated = await repair_managed_panel_art(message, "self_roles:colors")

        self.assertTrue(updated)
        edited = message.edit.await_args.kwargs
        self.assertEqual(edited["embed"].image.url, f"attachment://{new_name}")
        self.assertEqual([item.filename for item in edited["attachments"]], ["keep_this.txt", new_name])

    async def test_discord_embedded_gif_is_current_without_attachment_listing(self):
        from Commands.panels import _managed_panel_art_filename, managed_panel_art_is_current

        filename = _managed_panel_art_filename("self_roles:colors")
        embed = discord.Embed(title="Color Roles")
        embed.set_image(url=f"https://cdn.discordapp.com/attachments/12/34/{filename}?ex=abc")
        message = SimpleNamespace(
            channel=SimpleNamespace(id=12),
            embeds=[embed],
            attachments=[],
            edit=AsyncMock(),
        )
        self.assertTrue(managed_panel_art_is_current(message, "self_roles:colors"))
        self.assertFalse(await repair_managed_panel_art(message, "self_roles:colors"))
        message.edit.assert_not_awaited()

    async def test_local_panel_art_is_uploaded_as_a_message_attachment(self):
        sent = {}

        class Channel:
            async def send(self, **kwargs):
                sent.update(kwargs)
                return SimpleNamespace()

        with TemporaryDirectory() as temp_dir:
            art_path = Path(temp_dir) / "verification.png"
            art_path.write_bytes(b"test image contents")
            with patch.dict(
                "Commands.panels.PANEL_ART_IMAGES",
                {"verification": art_path},
                clear=False,
            ):
                await send_panel_with_local_art(
                    "verification",
                    Channel(),
                    embed=discord.Embed(title="Verify"),
                    view=object(),
                )

        self.assertEqual(
            sent["embed"].image.url,
            f"attachment://{sent['file'].filename}",
        )
        self.assertRegex(sent["file"].filename, r"^project_l_verification_[0-9a-f]{10}\.png$")

    async def test_missing_local_panel_art_uses_text_only_embed(self):
        sent = {}

        class Channel:
            async def send(self, **kwargs):
                sent.update(kwargs)
                return SimpleNamespace()

        with patch.dict(
            "Commands.panels.PANEL_ART_IMAGES",
            {"tickets": Path("does-not-exist.png")},
            clear=False,
        ):
            await send_panel_with_local_art(
                "tickets",
                Channel(),
                embed=discord.Embed(title="Tickets"),
                view=object(),
            )

        self.assertNotIn("file", sent)
        self.assertFalse(sent["embed"].image.url)

    async def test_panel_installation_is_idempotent(self):
        bot_user = SimpleNamespace(id=42)

        class FakeChannel:
            def __init__(self):
                self.messages = []

            def history(self, **_kwargs):
                async def iterate():
                    for item in reversed(self.messages):
                        yield item

                return iterate()

            async def send(self, *, embed, view, **_kwargs):
                image_file = _kwargs.get("file")
                message = SimpleNamespace(
                    author=bot_user,
                    embeds=[embed],
                    components=[SimpleNamespace(children=view.children)],
                    attachments=(
                        [SimpleNamespace(filename=image_file.filename)]
                        if image_file is not None
                        else []
                    ),
                )
                self.messages.append(message)
                return message

        panel_channel = FakeChannel()
        welcome_channel = FakeChannel()
        guild = SimpleNamespace(
            name="Test Server",
            me=None,
            get_channel=lambda channel_id: {99: panel_channel, 100: welcome_channel}.get(channel_id),
        )
        client = SimpleNamespace(
            user=bot_user,
            colour=discord.Colour.green(),
            get_guild=lambda guild_id: guild if guild_id == 7 else None,
            get_channel=lambda _channel_id: None,
        )
        config = {
            "guildId": 7,
            "welcome": 100,
            "managedResources": {"panelsChannel": 99},
        }
        with (
            patch("Commands.panels.load_config", return_value=config),
            patch("Commands.panels.load_role_ids", return_value=[]),
        ):
            first = await ensure_automatic_panels(client)
            second = await ensure_automatic_panels(client)

        self.assertEqual(first.created, ["verification", "private_voice", "public_voice", "tickets"])
        self.assertEqual(first.failed, [])
        self.assertEqual(second.created, [])
        self.assertEqual(
            second.existing,
            ["verification", "private_voice", "public_voice", "tickets"],
        )
        self.assertEqual(len(panel_channel.messages), 3)
        self.assertEqual(len(welcome_channel.messages), 1)
        self.assertEqual(
            panel_kind_for_message(welcome_channel.messages[0], bot_user.id),
            "verification",
        )

    async def test_misplaced_verify_is_removed_only_after_welcome_copy(self):
        bot_user = SimpleNamespace(id=42)
        old_verify = SimpleNamespace(
            author=bot_user,
            components=[SimpleNamespace(children=[SimpleNamespace(custom_id="verify")])],
            delete=AsyncMock(),
        )

        class Channel:
            def __init__(self, messages):
                self.messages = messages

            async def history(self, **_kwargs):
                for message in self.messages:
                    yield message

        panel_channel = Channel([old_verify])
        welcome_channel = Channel([])
        guild = SimpleNamespace(
            me=None,
            get_channel=lambda channel_id: {99: panel_channel, 100: welcome_channel}.get(channel_id),
        )
        client = SimpleNamespace(
            user=bot_user,
            colour=discord.Colour.green(),
            get_guild=lambda _id: guild,
            get_channel=lambda _id: None,
        )
        config = {"guildId": 7, "welcome": 100, "managedResources": {"panelsChannel": 99}}
        with (
            patch("Commands.panels.load_config", return_value=config),
            patch("Commands.panels.load_role_ids", return_value=[]),
            patch("Commands.panels.send_managed_panel", new_callable=AsyncMock) as send,
        ):
            report = await ensure_automatic_panels(client)

        self.assertEqual(send.await_args_list[0].args[:2], ("verification", welcome_channel))
        old_verify.delete.assert_awaited_once()
        self.assertEqual(report.moved, ["verification"])

    async def test_voice_and_ticket_panels_move_to_dedicated_channels(self):
        bot_user = SimpleNamespace(id=42)

        def old_panel(custom_id):
            return SimpleNamespace(
                author=bot_user,
                components=[SimpleNamespace(children=[SimpleNamespace(custom_id=custom_id)])],
                delete=AsyncMock(),
            )

        old_voice = old_panel("voicechannel")
        old_ticket = SimpleNamespace(
            author=bot_user,
            components=[SimpleNamespace(children=[
                SimpleNamespace(custom_id=custom_id)
                for custom_id in ("ticket_help", "ticket_suggestions", "ticket_report")
            ])],
            delete=AsyncMock(),
        )

        class Channel:
            def __init__(self, messages=()):
                self.messages = messages

            async def history(self, **_kwargs):
                for message in self.messages:
                    yield message

        channels = {99: Channel([old_voice, old_ticket]), 100: Channel(), 101: Channel(), 102: Channel()}
        guild = SimpleNamespace(get_channel=channels.get)
        client = SimpleNamespace(
            user=bot_user, colour=discord.Colour.green(),
            get_guild=lambda _id: guild, get_channel=lambda _id: None,
        )
        config = {"guildId": 7, "welcome": 100, "managedResources": {
            "panelsChannel": 99, "privateVoicePanelChannel": 101, "helpChannel": 102,
        }}
        with (
            patch("Commands.panels.load_config", return_value=config),
            patch("Commands.panels.load_role_ids", return_value=[]),
            patch("Commands.panels.send_managed_panel", new_callable=AsyncMock) as send,
        ):
            report = await ensure_automatic_panels(client)

        self.assertIn(("private_voice", channels[101]), [call.args[:2] for call in send.await_args_list])
        self.assertIn(("tickets", channels[102]), [call.args[:2] for call in send.await_args_list])
        old_voice.delete.assert_awaited_once()
        old_ticket.delete.assert_awaited_once()
        self.assertEqual(report.moved, ["private_voice", "tickets"])

    async def test_misplaced_verify_is_kept_if_welcome_post_fails(self):
        bot_user = SimpleNamespace(id=42)
        old_verify = SimpleNamespace(
            author=bot_user,
            components=[SimpleNamespace(children=[SimpleNamespace(custom_id="verify")])],
            delete=AsyncMock(),
        )

        class Channel:
            def __init__(self, messages):
                self.messages = messages

            async def history(self, **_kwargs):
                for message in self.messages:
                    yield message

        panel_channel = Channel([old_verify])
        welcome_channel = Channel([])
        guild = SimpleNamespace(
            me=None,
            get_channel=lambda channel_id: {99: panel_channel, 100: welcome_channel}.get(channel_id),
        )
        client = SimpleNamespace(
            user=bot_user,
            colour=discord.Colour.green(),
            get_guild=lambda _id: guild,
            get_channel=lambda _id: None,
        )
        config = {"guildId": 7, "welcome": 100, "managedResources": {"panelsChannel": 99}}

        async def send(kind, *_args):
            if kind == "verification":
                raise OSError("cannot send")

        with (
            patch("Commands.panels.load_config", return_value=config),
            patch("Commands.panels.load_role_ids", return_value=[]),
            patch("Commands.panels.send_managed_panel", side_effect=send),
        ):
            report = await ensure_automatic_panels(client)

        old_verify.delete.assert_not_awaited()
        self.assertIn("verification in welcome channel", report.failed)


if __name__ == "__main__":
    unittest.main()
