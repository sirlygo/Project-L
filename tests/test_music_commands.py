"""Music commands must resolve audio in /play, not /join."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from Commands.music import Start


class MusicCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_join_only_connects_to_the_users_voice_channel(self):
        channel = SimpleNamespace(id=10, name="Music", connect=AsyncMock())
        member = SimpleNamespace(voice=SimpleNamespace(channel=channel))
        guild = SimpleNamespace(get_member=lambda _id: member)
        interaction = SimpleNamespace(
            guild=guild, user=SimpleNamespace(id=4),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        cog = Start(SimpleNamespace(voice_clients=[]))
        with patch("Commands.music.print_interaction_info"), \
             patch("Commands.music.extract_playable_info") as extract:
            await Start.join.callback(cog, interaction)
        channel.connect.assert_awaited_once()
        extract.assert_not_called()
        interaction.response.send_message.assert_awaited_once()

    async def test_play_extracts_and_probes_before_starting_audio(self):
        guild = SimpleNamespace()
        voice = SimpleNamespace(
            guild=guild, is_connected=Mock(return_value=True),
            is_playing=Mock(return_value=False), move_to=AsyncMock(), play=Mock(),
        )
        channel = SimpleNamespace(id=10, name="Music", connect=AsyncMock(return_value=voice))
        member = SimpleNamespace(voice=SimpleNamespace(channel=channel))
        guild.get_member = lambda _id: member
        interaction = SimpleNamespace(
            guild=guild, user=SimpleNamespace(id=4),
            response=SimpleNamespace(defer=AsyncMock()),
            followup=SimpleNamespace(send=AsyncMock()),
        )
        cog = Start(SimpleNamespace(voice_clients=[voice]))
        url = "https://www.youtube.com/watch?v=example"
        source = object()
        with patch("Commands.music.print_interaction_info"), \
             patch("Commands.music.shutil.which", return_value="ffmpeg"), \
             patch("Commands.music.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=[{"url": "https://audio.example/stream"}, None]) as to_thread, \
             patch("Commands.music.discord.FFmpegPCMAudio", return_value=source):
            await Start.play.callback(cog, interaction, url)
        self.assertEqual(to_thread.await_count, 2)
        voice.play.assert_called_once()
        self.assertIs(voice.play.call_args.args[0], source)
        interaction.followup.send.assert_awaited_once()

