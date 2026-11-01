"""Standalone tests for patched-firmware status readback."""
import importlib.util
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, call, patch

API_PATH = Path(__file__).parents[1] / "custom_components" / "avr1710" / "api.py"
SPEC = importlib.util.spec_from_file_location("avr1710_api", API_PATH)
api = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = api
SPEC.loader.exec_module(api)


def poll_replies(*values):
    return [
        {"name": name, "para": value}
        for name, value in zip(("power", "source", "volume", "mute"), values)
    ]


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
        self.client.send_command.return_value = {"name": "volume", "para": ""}
        self.assertIsNone(await self.client.get_volume())
        self.client.send_command.return_value = {"name": "mute", "para": ""}
        self.assertIsNone(await self.client.get_mute())

    async def test_invalid_values_raise(self):
        for value in ("-1", "101", "58.5", "on", " "):
            with self.subTest(volume=value):
                self.client.send_command.return_value = {"name": "volume", "para": value}
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.get_volume()
        self.client.send_command.return_value = {"name": "mute", "para": "invalid"}
        with self.assertRaises(api.AVR1710ResponseError):
            await self.client.get_mute()

    async def test_combined_poll_tracks_changes(self):
        self.client.send_command.side_effect = (
            poll_replies("on", "TV", "61", "off") + poll_replies("on", "TV", "58", "on")
        )
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
        self.client.send_command.return_value = {"name": "power", "para": "off"}
        status = await self.client.async_update_status()
        self.assertFalse(status.power_on)
        self.assertIsNone(status.volume_level)
        self.assertIsNone(status.is_volume_muted)
        self.client.send_command.assert_awaited_once_with("query-status", para="power")

    async def test_auxiliary_failure_preserves_confirmed_power(self):
        previous = api.AVR1710Status(
            power_on=True, source="TV", volume_level=0.58, is_volume_muted=True,
        )
        for index in range(3):
            for error_type in (api.AVR1710ConnectionError, api.AVR1710ResponseError):
                with self.subTest(query=index, error=error_type):
                    self.client.send_command.side_effect = [
                        *poll_replies("on", "TV", "58")[:index + 1],
                        error_type("Transient failure"),
                    ]
                    with self.assertLogs("avr1710_api", level="WARNING"):
                        status = await self.client.async_update_status(previous=previous)
                    self.assertTrue(status.power_on)
                    self.assertEqual(status.source, "TV")
                    self.assertEqual(status.volume_level, 0.58)
                    self.assertTrue(status.is_volume_muted)
                    self.assertIsNot(status, previous)

    async def test_power_connection_failure_raises_instead_of_off(self):
        self.client.send_command.side_effect = api.AVR1710ConnectionError("Port busy")
        with self.assertRaises(api.AVR1710ConnectionError):
            await self.client.async_update_status(previous=api.AVR1710Status(power_on=True))

    async def test_invalid_power_reply_raises_instead_of_off(self):
        for value in ("", "unknown", "power"):
            with self.subTest(value=value):
                self.client.send_command.return_value = {"name": "power", "para": value}
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.async_update_status(previous=api.AVR1710Status(power_on=True))

    async def test_explicit_off_clears_previous_attributes(self):
        self.client.send_command.return_value = {"name": "power", "para": "off"}
        status = await self.client.async_update_status(previous=api.AVR1710Status(
            power_on=True, source="TV", volume_level=0.58, is_volume_muted=True,
        ))
        self.assertEqual(status, api.AVR1710Status(power_on=False))

    async def test_partial_update_keeps_new_values_and_recovers(self):
        previous = api.AVR1710Status(
            power_on=True, source="TV", volume_level=0.58, is_volume_muted=False,
        )
        self.client.send_command.side_effect = [
            *poll_replies("on", "Radio", "61"),
            api.AVR1710ConnectionError("Port busy"),
        ]
        with self.assertLogs("avr1710_api", level="WARNING"):
            status = await self.client.async_update_status(previous=previous)
        self.assertEqual(status.source, "Radio")
        self.assertEqual(status.volume_level, 0.61)
        self.assertFalse(status.is_volume_muted)
        self.assertEqual(previous.source, "TV")
        self.assertEqual(previous.volume_level, 0.58)
        self.client.send_command.side_effect = poll_replies("on", "Radio", "61", "on")
        recovered = await self.client.async_update_status(previous=status)
        self.assertTrue(recovered.is_volume_muted)

    async def test_missing_and_echoed_status_are_rejected(self):
        for reply in ({}, {"name": "power"}, {"name": "query-status", "para": "power"}):
            with self.subTest(reply=reply):
                self.client.send_command.return_value = reply
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.query_status("power")


class VolumeSliderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = api.AVR1710Client("192.0.2.1")
        self.client.get_power = AsyncMock(return_value=True)
        self.client.get_volume = AsyncMock()
        self.client.volume_up = AsyncMock()
        self.client.volume_down = AsyncMock()
        sleep = patch.object(api.asyncio, "sleep", new_callable=AsyncMock)
        sleep.start()
        self.addCleanup(sleep.stop)

    async def test_reaches_target_in_both_directions(self):
        for readings, target, command in (
            ([0.54, 0.54, 0.55, 0.56], 0.56, self.client.volume_up),
            ([0.56, 0.55, 0.54], 0.54, self.client.volume_down),
            ([0.01, 0.0], 0.0, self.client.volume_down),
            ([0.99, 1.0], 1.0, self.client.volume_up),
        ):
            with self.subTest(target=target):
                command.reset_mock()
                self.client.get_volume.side_effect = readings
                await self.client.set_volume(target)
                self.assertEqual(command.await_count, len(readings) - 1)

    async def test_already_at_target_sends_no_steps(self):
        self.client.get_volume.return_value = 0.54
        await self.client.set_volume(0.54)
        self.client.volume_up.assert_not_awaited()
        self.client.volume_down.assert_not_awaited()

    async def test_invalid_targets_send_no_commands(self):
        for target in (-0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    await self.client.set_volume(target)
        self.client.get_power.assert_not_awaited()

    async def test_stalled_volume_stops(self):
        self.client.get_volume.return_value = 0.54
        with self.assertRaisesRegex(api.AVR1710ResponseError, "stopped changing"):
            await self.client.set_volume(0.6)
        self.assertEqual(self.client.volume_up.await_count, 4)

    async def test_missing_readback_stops_without_blind_steps(self):
        for readings, expected_steps in (([None], 0), ([0.54, None], 1)):
            with self.subTest(readings=readings):
                self.client.volume_up.reset_mock()
                self.client.get_volume.side_effect = readings
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.set_volume(0.6)
                self.assertEqual(self.client.volume_up.await_count, expected_steps)

    async def test_power_off_prevents_and_interrupts_adjustment(self):
        for powers, steps in (([False], 0), ([True, False], 1)):
            with self.subTest(powers=powers):
                self.client.volume_up.reset_mock()
                self.client.get_power.side_effect = powers
                self.client.get_volume.return_value = 0.54
                with self.assertRaises(api.AVR1710ResponseError):
                    await self.client.set_volume(0.6)
                self.assertEqual(self.client.volume_up.await_count, steps)

    async def test_opposite_movement_stops(self):
        self.client.get_volume.side_effect = [0.54, 0.53]
        with self.assertRaisesRegex(api.AVR1710ResponseError, "opposite"):
            await self.client.set_volume(0.6)
        self.client.volume_up.assert_awaited_once()

    async def test_connection_failure_stops_steps(self):
        self.client.get_volume.side_effect = [
            0.54, api.AVR1710ConnectionError("Port busy"),
        ]
        with self.assertRaises(api.AVR1710ConnectionError):
            await self.client.set_volume(0.6)
        self.client.volume_up.assert_awaited_once()


class ConnectionPacingTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovers_from_multi_second_listener_interruption(self):
        reader = Mock()
        reader.read = AsyncMock(return_value=b"<name>power</name><para>on</para>")
        writer = Mock()
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()
        client = api.AVR1710Client("192.0.2.1")
        with (
            patch.object(api.asyncio, "open_connection", side_effect=[
                ConnectionRefusedError("Listener busy"),
                ConnectionRefusedError("Listener busy"),
                ConnectionRefusedError("Listener busy"),
                ConnectionRefusedError("Listener busy"),
                (reader, writer),
            ]) as connect,
            patch.object(api.asyncio, "sleep", new_callable=AsyncMock) as sleep,
        ):
            self.assertTrue(await client.get_power())
        self.assertEqual(connect.await_count, 5)
        delays = [item.args[0] for item in sleep.await_args_list if item.args[0] > 0]
        self.assertEqual(delays, [0.4, 0.8, 1.6, 3.2])

    async def test_next_connection_waits_for_slot_release(self):
        opened = []
        reader = Mock()
        reader.read = AsyncMock(return_value=b"<name>power</name><para>on</para>")
        writer = Mock()
        writer.drain = AsyncMock()
        writer.wait_closed = AsyncMock()

        async def open_connection(*args):
            opened.append(time.monotonic())
            return reader, writer

        client = api.AVR1710Client("192.0.2.1")
        with (
            patch.object(api.asyncio, "open_connection", side_effect=open_connection),
            patch.object(api, "CONTROL_RECONNECT_DELAY", 0.02),
        ):
            await client.get_power()
            await client.get_power()
        self.assertGreaterEqual(opened[1] - opened[0], 0.02)
        self.assertEqual(writer.close.call_count, 2)
