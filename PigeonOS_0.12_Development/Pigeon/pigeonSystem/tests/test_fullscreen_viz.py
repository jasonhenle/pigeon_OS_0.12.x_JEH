"""Fullscreen visualizer: presets / config, metering calibration, rendering at full size and zone 6."""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

from pigeon import fullscreen_viz as fv  # noqa: E402
from pigeon import zone4_eq  # noqa: E402

SR = 48_000


def _sine(dbfs_rms: float, seconds: float, left: bool = True, right: bool = True) -> np.ndarray:
    t = np.arange(int(SR * seconds)) / SR
    x = (10 ** (dbfs_rms / 20) * math.sqrt(2) * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    return np.stack((x if left else 0 * x, x if right else 0 * x), axis=1)


class _Feed:
    """Feeds a buffer into the PCM ring one frame's worth at a time."""

    def __init__(self, buf: np.ndarray) -> None:
        self.buf, self.pos = buf, 0

    def step(self, dt: float = 1 / 30) -> None:
        n = int(SR * dt)
        idx = (self.pos + np.arange(n)) % self.buf.shape[0]
        self.pos = (self.pos + n) % self.buf.shape[0]
        zone4_eq.feed_pcm_stereo(self.buf[idx, 0], self.buf[idx, 1], float(SR))


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        patches = [
            mock.patch.object(fv, "config_path", lambda: Path(self._tmp.name) / fv.CONFIG_NAME),
            mock.patch.object(zone4_eq, "want_mic_capture", lambda: None),
            # Metering checks read calibrated levels: no visualizer input gain.
            mock.patch.object(zone4_eq, "input_gain_db", lambda: 0.0),
            mock.patch.object(fv, "theme_hex", lambda: fv.THEME_BLUE),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        fv._cfg_checked = 0.0
        fv._cfg_mtime = -1
        silence = np.zeros(zone4_eq.RING_SIZE, np.float32)  # no audio left over from another test
        zone4_eq.feed_pcm_stereo(silence, silence, float(SR))
        fv.set_presets(None)
        self.addCleanup(fv.set_presets, None)
        self.addCleanup(self._tmp.cleanup)


class PresetTests(_Base):
    def test_default_presets_have_distinct_names_and_live_styles(self) -> None:
        names = [p["name"] for p in fv.presets()]
        self.assertEqual(len(names), len(set(names)))
        self.assertLessEqual({p["style"] for p in fv.presets()}, set(fv.STYLES))
        self.assertEqual(names[0], "Spectrum")

    def test_retired_style_and_stale_keys_drop_out(self) -> None:
        fv.config_path().write_text(json.dumps({"presets": [
            {"name": "Old", "style": "scope"}, {"name": "B", "style": "led_ladder", "readouts": True}]}))
        items, _ = fv.load_config()
        self.assertEqual([p["name"] for p in items], ["B"])
        self.assertNotIn("readouts", items[0])

    def test_rotation_is_spectrum_and_lab_starters_render(self) -> None:
        self.assertEqual([p["name"] for p in fv.presets()], ["Spectrum", "Sweep VU", "Arc VU", "Stereo Bars"])
        names = [d["name"] for d in fv.LAB_PRESETS]
        self.assertEqual(len(names), len(set(names)))
        buf = np.zeros((400, 640, 3), np.uint8)
        fv.set_presets([fv.complete_preset(dict(d)) for d in fv.LAB_PRESETS])
        self.addCleanup(fv.set_presets, None)
        for i in range(len(names)):
            fv.FullscreenViz(i).render(buf, toast=False)
            self.assertGreater(int(buf.max()), 0, names[i])

    def test_sweep_vu_wedges_follow_the_theme_and_wear_the_badge(self) -> None:
        sweep = next(p for p in fv.presets() if p["name"] == "Sweep VU")
        self.assertEqual(fv.themed(sweep, "#00A22D")["segColor"], "#00A22D")
        self.assertIsNotNone(fv._wordmark_ink())
        g = fv.ArcVU._geo(sweep)
        cy = int(g["y0"] + g["H"] - g["cover"] / 2.0)
        cx = int(g["x0"] + g["W"] / 2.0)
        base = fv.ArcVU().layers(sweep, fv.DESIGN_W, fv.DESIGN_H)["base"]
        plain = fv.ArcVU().layers(dict(sweep, brand=False), fv.DESIGN_W, fv.DESIGN_H)["base"]
        box = (slice(cy - 20, cy + 20), slice(cx - 60, cx + 60))
        self.assertGreater(int(base[box].max()), 60, "badge drawn on the cover")
        self.assertEqual(int(plain[box].max()), 0)

    def test_arc_vu_sits_on_the_sweep_vu_meters(self) -> None:
        by = {p["name"]: p for p in fv.presets()}
        sweep, arc = by["Sweep VU"], by["Arc VU"]
        g = fv.ArcVU._geo(sweep)
        pivots = [(g["x0"] + m * (g["W"] + g["gap"]) + g["W"] / 2.0, g["y0"] + g["piv"]) for m in range(2)]
        self.assertEqual([m[:2] for m in fv.SweepVU._meters(arc)], pivots)
        self.assertEqual(arc["sweepDeg"], sweep["sweepDeg"])
        r_out = g["R"] + 6.0
        self.assertAlmostEqual(arc["arcR"], r_out - sweep["segLen"] / 2.0)
        self.assertEqual(arc["bandW"], sweep["segLen"])

    def test_text_is_off_by_default(self) -> None:
        for p in fv.presets() + [fv.complete_preset(dict(d)) for d in fv.LAB_PRESETS]:
            if "showText" in fv.style_specs(str(p["style"])):
                self.assertFalse(p["showText"], p["name"])

    def test_file_overrides_merge_over_style_defaults(self) -> None:
        fv.config_path().write_text(json.dumps(
            {"active": 1, "presets": [{"name": "A", "style": "bars", "bands": 12}, {"name": "B", "style": "rta"}]}))
        items, active = fv.load_config()
        self.assertEqual(active, 1)
        self.assertEqual(items[0]["bands"], 12)
        self.assertEqual(items[0]["colA"], fv.STYLES["bars"]["params"]["colA"][0])  # type: ignore[index]
        self.assertIn("fftSize", items[0])

    def test_saved_retired_default_picks_up_the_new_one(self) -> None:
        fv.config_path().write_text(json.dumps({"presets": [
            {"name": "Old", "style": "sweep_vu", "track": "#1a1a1a"},
            {"name": "Tuned", "style": "sweep_vu", "track": "#123456"}]}))
        items, _ = fv.load_config()
        self.assertEqual(items[0]["track"], fv.STYLES["sweep_vu"]["params"]["track"][0])  # type: ignore[index]
        self.assertEqual(items[1]["track"], "#123456")
        fv.config_path().write_text(json.dumps({"presets": [{"name": "Bars", "style": "bars", "showSlots": True}]}))
        fv._cfg_checked = 0.0
        self.assertFalse(fv.load_config()[0][0]["showSlots"])

    def test_bad_file_falls_back_to_defaults(self) -> None:
        fv.config_path().write_text("{not json")
        self.assertEqual(len(fv.load_config()[0]), len(fv.DEFAULT_PRESETS))

    def test_save_round_trips(self) -> None:
        items = fv.default_presets() + [fv.complete_preset(dict(d)) for d in fv.LAB_PRESETS]
        items[2]["name"] = "Bridge"
        fv.save_config(items, 2)
        fv._cfg_checked = 0.0
        got, active = fv.load_config()
        self.assertEqual((got[2]["name"], active), ("Bridge", 2))

    def test_rotate_wraps_both_ways(self) -> None:
        items = [fv.complete_preset(dict(d)) for d in fv.DEFAULT_PRESETS + fv.LAB_PRESETS]
        fv.set_presets(items)
        self.addCleanup(fv.set_presets, None)
        viz = fv.FullscreenViz(0)
        viz.rotate(-1)
        self.assertEqual(viz.index, len(items) - 1)
        viz.rotate(2)
        self.assertEqual(viz.index, 1)


def _viz_for(style: str) -> fv.FullscreenViz:
    """A visualizer showing one preset of ``style`` (defaults)."""
    fv.set_presets([fv.complete_preset({"style": style})])
    return fv.FullscreenViz(0)


class ThemeTests(_Base):
    def test_stock_blues_follow_the_theme_others_stay(self) -> None:
        spectrum = fv.complete_preset(fv.DEFAULT_PRESETS[0])
        red = fv.themed(spectrum, "#FF3B30")
        self.assertEqual(red["colA"], "#FF3B30")
        self.assertEqual(red["colB"], fv._mix_hex("#FF3B30", "#FFFFFF", 0.58))
        self.assertEqual(red["peakColor"], spectrum["peakColor"])
        sweep = fv.themed(fv.complete_preset({"style": "sweep_vu"}), "#3DDC84")
        self.assertEqual(sweep["lit"], "#3DDC84")
        self.assertEqual(sweep["fillColor"], fv._mix_hex("#3DDC84", "#000000", 0.53))
        self.assertEqual(sweep["red"], "#FF3B30")

    def test_default_theme_and_tuned_colours_unchanged(self) -> None:
        spectrum = fv.complete_preset(fv.DEFAULT_PRESETS[0])
        self.assertIs(fv.themed(spectrum, fv.THEME_BLUE), spectrum)
        tuned = dict(spectrum, colA="#123456")
        self.assertEqual(fv.themed(tuned, "#FF3B30")["colA"], "#123456")

    def test_active_preset_uses_the_live_ui_colour(self) -> None:
        fv.set_presets(fv.default_presets())
        with mock.patch.object(fv, "theme_hex", lambda: "#FF3B30"):
            self.assertEqual(fv.FullscreenViz(0).preset()["colA"], "#FF3B30")
        self.assertEqual(fv.presets()[0]["colA"], fv.THEME_BLUE, "saved presets keep the stock colour")


class MeteringTests(_Base):
    def _run(self, viz: fv.FullscreenViz, feed: _Feed, seconds: float) -> None:
        out = np.zeros((200, 320, 3), np.uint8)
        for _ in range(int(seconds * 30)):
            feed.step()
            viz._last_t = time.monotonic() - 1 / 30
            viz.render(out, capture=False, toast=False)

    def test_vu_reads_zero_at_reference_level(self) -> None:
        viz = _viz_for("pixel_vu")  # 0 VU = −18 dBFS
        self._run(viz, _Feed(_sine(-18.0, 1.0)), 1.5)
        np.testing.assert_allclose(viz.analysis.vu, [1.0, 1.0], atol=0.02)

    def test_vu_left_only(self) -> None:
        viz = _viz_for("sweep_vu")
        self._run(viz, _Feed(_sine(-18.0, 1.0, right=False)), 1.5)
        self.assertGreater(viz.analysis.vu[0], 0.95)
        self.assertLess(viz.analysis.vu[1], 0.05)

    def test_digital_vu_lights_to_zero_vu(self) -> None:
        viz = _viz_for("arc_vu")
        self._run(viz, _Feed(_sine(-18.0, 1.0)), 1.5)
        L = next(iter(viz._layers.values()))
        lit = int(np.searchsorted(L["pos"], viz.analysis.vu[0] / 1.4125, side="right"))
        self.assertAlmostEqual(lit / L["pos"].size, 1 / 1.4125, delta=1.5 / L["pos"].size)

    def test_ppm_reads_sine_peak(self) -> None:
        viz = _viz_for("led_ladder")
        self._run(viz, _Feed(_sine(-9.0, 1.0)), 1.0)
        np.testing.assert_allclose(viz.analysis.ppm, [-6.0, -6.0], atol=0.2)  # peak = rms + 3 dB

    def test_bounce_throws_balls_up(self) -> None:
        viz = _viz_for("bounce")
        self._run(viz, _Feed(_sine(-10.0, 1.0)), 0.3)
        self.assertGreater(float(viz.analysis.state["bounce"]["h"].max()), 0.05)


class RenderTests(_Base):
    def test_every_preset_draws_at_full_and_zone6(self) -> None:
        feed = _Feed(_sine(-10.0, 1.0))
        viz = fv.FullscreenViz(0)
        for i in range(len(fv.presets())):
            viz.set_index(i, toast=True)
            full = np.zeros((fv.DESIGN_H, fv.DESIGN_W, 3), np.uint8)
            app = np.full((fv.DESIGN_H, fv.DESIGN_W, 4), 7, np.uint8)
            for _ in range(5):
                feed.step()
                viz.render(full, capture=False)
                viz.render(app, fv.ZONE6_RECT, capture=False)
            self.assertGreater(int(full.max()), 0, fv.presets()[i]["name"])
            x, y, w, h, _r = fv.ZONE6_RECT
            self.assertTrue((app[y + h // 2, x + w // 2, 3] == 255))
            self.assertTrue((app[5, 5] == 7).all(), "nothing outside the zone-6 box")
            # Rounded corner: the outermost pixel keeps what was under it.
            self.assertTrue((app[y, x, :3] == 7).all())

    def test_clear_render_draws_over_the_page_with_no_fill(self) -> None:
        feed = _Feed(_sine(-10.0, 1.0))
        page = (90, 60, 30)
        x, y, w, h, _r = fv.ZONE6_RECT
        for style in ("pixel_vu", "sweep_vu", "bars", "led_ladder", "rta", "dots", "bounce", "fireflies"):
            viz = _viz_for(style)
            out = np.empty((fv.DESIGN_H, fv.DESIGN_W, 4), np.uint8)
            for _ in range(5):
                feed.step()
                out[:, :, :3] = page
                out[:, :, 3] = 7
                viz.render(out, fv.ZONE6_RECT, capture=False, toast=False, clear=True)
            box = out[y : y + h, x : x + w, :3]
            shows = np.all(box == page, axis=2)
            self.assertGreater(float(shows.mean()), 0.2, f"{style}: page hidden under a fill")
            self.assertGreater(float((~shows).mean()), 0.005, f"{style}: nothing drawn")
            self.assertTrue((out[y + 1, x + 1, :3] == page).all(), style)  # corner keeps the page
            self.assertTrue((out[5, 5] == (*page, 7)).all(), "nothing outside the zone-6 box")

    def test_text_switch_changes_the_art(self) -> None:
        for style, layer in (("pixel_vu", "lo"), ("arc_vu", "base"), ("sweep_vu", "base"),
                             ("led_ladder", "base"), ("rta", "base")):
            p = fv.complete_preset({"style": style})
            off = fv.STYLE_IMPLS[style].layers(p, 640, 400)[layer]
            on = fv.STYLE_IMPLS[style].layers(dict(p, showText=True), 640, 400)[layer]
            self.assertTrue((off != on).any(), style)

    def test_rta_cells_are_square(self) -> None:
        for band_set in ("10 (octave)", "31 (1/3 oct)", "61 (1/6 oct)"):
            p = fv.complete_preset({"style": "rta", "bandSet": band_set})
            lad = fv.STYLE_IMPLS["rta"]._ladders(p, fv.Xf(fv.DESIGN_W, fv.DESIGN_H))[0]
            x0, y0, x1, y1 = lad.seg(0)
            self.assertAlmostEqual((y1 - y0) / (x1 - x0), 1.0, delta=0.08, msg=band_set)

    def test_bars_follow_signal(self) -> None:
        viz = _viz_for("bars")
        out = np.zeros((fv.DESIGN_H, fv.DESIGN_W, 3), np.uint8)
        viz.render(out, capture=False, toast=False)
        quiet = out.copy()
        feed = _Feed(_sine(-6.0, 1.0))
        for _ in range(10):
            feed.step()
            viz._last_t = time.monotonic() - 1 / 30
            viz.render(out, capture=False, toast=False)
        self.assertGreater(int(np.count_nonzero(out != quiet)), 1000)


if __name__ == "__main__":
    unittest.main()
