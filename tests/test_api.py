"""Standalone tests for patched-firmware status readback."""
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call

API_PATH = Path(__file__).parents[1] / "custom_components" / "avr1710" / "api.py"
SPEC = importlib.util.spec_from_file_location("avr1710_api", API_PATH)
api = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api
SPEC.loader.exec_module(api)


class StatusTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = api.AVR1710Client("192.0.2.1")
        self.client.send_command = AsyncMock()

    async def test_volume_percentage_and_boundaries(self):
        for value, expected in (("0", 0.0), ("1", 0.01), ("58", 0.58), ("100", 1.0)):
            with self.subTest(value=value):
                self.client.send_command.return_value = {"name": "volume", "para": value}
                self.assertEqual(await self.client.get_volume(), expected)
        self.client.send_command.assert_awaited_with("query-status", para="volume")

    async def test_mute_states(self):
        for value, expected in (("on", True), ("off", False)):
            with self.subTest(value=value):
                self.client.send_command.return_value = {"name": "mute", "para": value}
                self.assertIs(await self.client.get_mute(), expected)
        self.client.send_command.assert_awaited_with("query-status", para="mute")

    async def test_older_firmware_empty_values(self):
        self.client.send_command.return_value = {"para": ""}
        self.assertIsNone(await self.client.get_volume())
        self.assertIsNone(await self.client.get_mute())

    async def test_invalid_values_raise(self):
        for value in ("-1", "101", "58.5", "on", " "):
            with self.subTest(volume=value):
                self.client.send_command.return_value = {"para": value}
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.get_volume()
        self.client.send_command.return_value = {"para": "invalid"}
        with self.assertRaises(api.AVR1710ResponseError):
            await self.client.get_mute()

    async def test_combined_poll_tracks_changes(self):
        self.client.send_command.side_effect = [
            {"para": "on"}, {"para": "TV"}, {"para": "61"}, {"para": "off"},
            {"para": "on"}, {"para": "TV"}, {"para": "58"}, {"para": "on"},
        ]
        first = await self.client.async_update_status()
        second = await self.client.async_update_status(previous=first)
        self.assertTrue(second.power_on)
        self.assertEqual(second.source, "TV")
        self.assertEqual(first.volume_level, 0.61)
        self.assertFalse(first.is_volume_muted)
        self.assertEqual(second.volume_level, 0.58)
        self.assertTrue(second.is_volume_muted)
        self.assertEqual(
            self.client.send_command.await_args_list,
            [call("query-status", para=item) for item in ("power", "source", "volume", "mute")] * 2,
        )

    async def test_power_off_skips_audio_queries(self):
        self.client.send_command.return_value = {"para": "off"}
        status = await self.client.async_update_status()
        self.assertFalse(status.power_on)
        self.assertIsNone(status.volume_level)
        self.assertIsNone(status.is_volume_muted)
        self.client.send_command.assert_awaited_once_with("query-status", para="power")

    async def test_connection_loss_clears_audio_state(self):
        previous = api.AVR1710Status(
            power_on=True, source="TV", volume_level=0.58, is_volume_muted=True,
        )
        self.client.send_command.side_effect = [
            {"para": "on"}, {"para": "TV"}, {"para": "58"},
            api.AVR1710ConnectionError("Receiver asleep"),
        ]
        status = await self.client.async_update_status(previous=previous)
        self.assertFalse(status.power_on)
        self.assertIsNone(status.source)
        self.assertIsNone(status.volume_level)
        self.assertIsNone(status.is_volume_muted)

    async def test_invalid_poll_is_not_reported_as_standby(self):
        self.client.send_command.side_effect = [
            {"para": "on"}, {"para": "TV"}, {"para": "101"},
        ]
        with self.assertRaises(api.AVR1710ResponseError):
            await self.client.async_update_status(previous=api.AVR1710Status(power_on=True))
