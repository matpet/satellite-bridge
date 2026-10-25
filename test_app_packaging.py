"""Packaging regressions: saved pairs survive first launch and app updates."""

import json
import os
import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bridge_paths import data_directory, prepare_data, instance_lock
from bridge_app import App
from bridge_core import Bridge, Pair
from test_bridge import FakeTransport, eventually, HOME, LEO, packet


class AppDataTests(unittest.TestCase):
    def test_import_preserves_all_pairs_and_does_not_overwrite_user_edits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            seed = root / "resources"
            seed.mkdir()
            original = {"presets": [{"name": "Digital"}, {"name": "My SSB"}], "home_id": "saved-id"}
            (seed / "bridge-settings.json").write_text(json.dumps(original))
            data = prepare_data(root / "support", seed)
            self.assertEqual(json.loads((data / "bridge-settings.json").read_text()), original)
            edited = {**original, "home_id": "user-edited"}
            (data / "bridge-settings.json").write_text(json.dumps(edited))
            prepare_data(data, seed)
            self.assertEqual(json.loads((data / "bridge-settings.json").read_text()), edited)

    def test_second_instance_cannot_take_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            lock = instance_lock(temporary)
            self.assertIsNotNone(lock)
            with lock:
                self.assertIsNone(instance_lock(temporary))
            with instance_lock(temporary) as next_lock:
                self.assertIsNotNone(next_lock)

    def test_data_location_can_be_isolated_without_changing_bundle(self):
        with patch.dict(os.environ, {"SATELLITE_BRIDGE_DATA_DIR": "/private/tmp/bridge-isolated"}):
            self.assertEqual(data_directory(), Path("/private/tmp/bridge-isolated"))


class StartupTests(unittest.TestCase):
    def make_app(self, guard=None, transport_factory=FakeTransport):
        app = App.__new__(App)
        app.settings = SimpleNamespace(data={
            "home_id": "ssb",
            "presets": [
                {"id": "ssb", "name": "SSB", **Pair.from_values("433.740", "144.240", "USB", "USB").view()},
                {"id": "digital", "name": "Digital", **HOME.view()},
            ],
        })
        app.selected_id = None
        app.select_pair = lambda preset: setattr(app, "selected_id", preset["id"])
        app.bridge = Bridge(transport_factory=transport_factory, power_guard=guard or (lambda force=False: 4), rx_filter=lambda mode, number: number)
        app.bridge.start(port=0)
        return app

    def test_startup_chooses_digital_over_last_pair_and_caps_before_tuning(self):
        order = []
        def guard(force=False):
            order.append("power")
            return 4
        class CheckedTransport(FakeTransport):
            def apply(self, pair, force=False):
                order.append("tune")
                super().apply(pair, force)
        app = self.make_app(guard, CheckedTransport)
        original = copy.deepcopy(app.settings.data)
        try:
            app.start_digital()
            eventually(lambda: app.bridge.applied == 1)
            self.assertEqual(app.selected_id, "digital")
            self.assertEqual(app.bridge.last_sent, HOME)
            self.assertEqual(app.bridge.source, "qo100")
            self.assertEqual(app.bridge.rx_filter_number, 1)
            self.assertLess(order.index("power"), order.index("tune"))
            self.assertGreaterEqual(order.count("power"), 2)
            self.assertTrue(app.bridge.snapshot()["power_cap_active"])
            self.assertEqual(app.settings.data, original)
        finally:
            app.bridge.close()

    def test_startup_blocks_incoming_packets_until_macdoppler_is_selected(self):
        app = self.make_app()
        try:
            app.bridge.ingest(packet())
            app.start_digital()
            for _ in range(40):
                app.bridge.ingest(packet())
            eventually(lambda: app.bridge.applied == 1)
            self.assertEqual(app.bridge.transport.calls, [(HOME, True)])
            self.assertEqual(app.bridge.ignored, 41)
            app.bridge.follow_macdoppler()
            eventually(lambda: app.bridge.last_sent == LEO)
            self.assertEqual(app.bridge.source, "macdoppler")
        finally:
            app.bridge.close()

    def test_deferred_startup_runs_after_ui_is_ready(self):
        app = self.make_app()
        app.shutting_down = False
        app.startup_epoch = app.bridge.epoch
        try:
            app.start_digital_if_unchanged()
            eventually(lambda: app.bridge.applied == 1)
            self.assertEqual(app.bridge.last_sent, HOME)
        finally:
            app.bridge.close()

    def test_deferred_startup_does_not_override_user_choice_or_shutdown(self):
        for closing in (False, True):
            with self.subTest(closing=closing):
                app = self.make_app()
                app.startup_epoch = app.bridge.epoch
                app.shutting_down = closing
                try:
                    if not closing:
                        app.bridge.follow_macdoppler()
                    app.start_digital_if_unchanged()
                    self.assertFalse(app.bridge.transport.calls)
                    self.assertIsNone(app.selected_id)
                    if not closing:
                        self.assertEqual(app.bridge.source, "macdoppler")
                finally:
                    app.bridge.close()

    def test_startup_power_failure_blocks_all_tuning_and_macdoppler(self):
        def unavailable(force=False):
            raise RuntimeError("Power verification unavailable")
        app = self.make_app(unavailable)
        try:
            app.start_digital()
            app.bridge.ingest(packet())
            eventually(lambda: bool(app.bridge.power_error))
            self.assertFalse(app.bridge.enabled)
            self.assertFalse(app.bridge.transport.calls)
            self.assertEqual(app.bridge.source, "qo100")
            self.assertTrue(app.bridge.snapshot()["power_cap_active"])
            self.assertEqual(app.bridge.ignored, 1)
        finally:
            app.bridge.close()

    def test_missing_or_ambiguous_digital_does_not_substitute_another_pair(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                app = self.make_app()
                if duplicate:
                    app.settings.data["presets"].append({"id": "duplicate", "name": "digital", **HOME.view()})
                else:
                    app.settings.data["presets"].pop()
                try:
                    app.start_digital()
                    app.bridge.ingest(packet())
                    self.assertFalse(app.bridge.enabled)
                    self.assertFalse(app.bridge.transport.calls)
                    self.assertEqual(app.bridge.source, "qo100")
                    self.assertIn("Digital", app.bridge.error)
                    self.assertIsNone(app.selected_id)
                finally:
                    app.bridge.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
