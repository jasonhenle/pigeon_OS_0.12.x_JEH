"""HDMI status LED follows a live video signal, not a stale OpenCV handle."""

from __future__ import annotations

import os
import sys
import unittest

_SYS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SYS_ROOT not in sys.path:
    sys.path.insert(0, _SYS_ROOT)

import numpy as np  # noqa: E402

from pigeon import hdmi_capture as ho  # noqa: E402


class _FakeCap:
    def __init__(self, frame=None, *, opened: bool = True, ok: bool = True):
        self.frame = frame
        self._opened = opened
        self.ok = ok
        self.released = False

    def isOpened(self) -> bool:
        return bool(self._opened)

    def read(self):
        return self.ok, self.frame

    def release(self) -> None:
        self.released = True
        self._opened = False


class HdmiPresenceLedTests(unittest.TestCase):
    def setUp(self) -> None:
        ho._cap = None
        ho._cap_index = None
        ho._hdmi_present = None
        ho._hdmi_no_signal_hits = 0
        ho._hdmi_probe_in_flight = False
        ho._hdmi_probe_mono = 0.0
        ho._av_devices_cache = None
        ho.reset_frame_schedule()

    def tearDown(self) -> None:
        ho._cap = None
        ho._hdmi_present = None
        ho._hdmi_no_signal_hits = 0
        ho._av_devices_cache = None

    def test_open_handle_does_not_keep_led_green(self) -> None:
        ho._hdmi_present = False
        ho._cap = _FakeCap(opened=True)
        self.assertFalse(ho.hdmi_capture_available())

    def test_note_present_drives_led(self) -> None:
        ho.note_hdmi_present(True)
        self.assertTrue(ho.hdmi_capture_available())
        ho.note_hdmi_present(False)
        self.assertFalse(ho.hdmi_capture_available())

    def test_black_frame_is_not_signal(self) -> None:
        black = np.zeros((1080, 1920, 3), dtype=np.uint8)
        self.assertFalse(ho._frame_has_video_signal(black))
        noisy = np.random.randint(0, 255, (180, 320, 3), dtype=np.uint8)
        self.assertTrue(ho._frame_has_video_signal(noisy))

    def test_failed_read_drops_presence(self) -> None:
        ho.note_hdmi_present(True)
        cap = _FakeCap(frame=None, opened=True, ok=False)
        ho._cap = cap
        original = ho._hdmi_device_enumerated
        ho._hdmi_device_enumerated = lambda: False  # type: ignore[method-assign]
        try:
            present = ho._probe_hdmi_now()
        finally:
            ho._hdmi_device_enumerated = original  # type: ignore[method-assign]
        self.assertFalse(present)
        self.assertFalse(ho.hdmi_capture_available())
        self.assertTrue(cap.released)

    def test_black_frames_drop_led_after_hysteresis(self) -> None:
        ho.note_hdmi_present(True)
        black = np.zeros((240, 320, 3), dtype=np.uint8)
        ho._cap = _FakeCap(frame=black, opened=True, ok=True)

        def _fail_enumerate() -> bool:
            raise AssertionError("black frames must use the open handle")

        original = ho._hdmi_device_enumerated
        ho._hdmi_device_enumerated = _fail_enumerate  # type: ignore[method-assign]
        try:
            first = ho._probe_hdmi_now()
            second = ho._probe_hdmi_now()
        finally:
            ho._hdmi_device_enumerated = original  # type: ignore[method-assign]
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertFalse(ho.hdmi_capture_available())

    def test_live_frame_keeps_led_green(self) -> None:
        ho.note_hdmi_present(False)
        noisy = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
        ho._cap = _FakeCap(frame=noisy, opened=True, ok=True)
        self.assertTrue(ho._probe_hdmi_now())
        self.assertTrue(ho.hdmi_capture_available())



class HdmiFrameCheckTests(unittest.TestCase):
    """Frame fingerprints still drive the HDMI clock saver after OCR was retired."""

    def setUp(self) -> None:
        ho.reset_frame_schedule()
        self._grab = ho._grab_frame

    def tearDown(self) -> None:
        ho._grab_frame = self._grab  # type: ignore[method-assign]
        ho.reset_frame_schedule()

    def test_check_cadence(self) -> None:
        self.assertTrue(ho.frame_check_due(now=100.0))
        self.assertFalse(ho.frame_check_due(now=100.0 + ho.FRAME_CHECK_INTERVAL_S - 0.1))
        self.assertTrue(ho.frame_check_due(now=100.0 + ho.FRAME_CHECK_INTERVAL_S))

    def test_unchanged_frames_arm_clock_saver(self) -> None:
        frame = np.random.randint(0, 255, (270, 480, 3), dtype=np.uint8)
        ho._grab_frame = lambda: frame  # type: ignore[method-assign]
        seen: list = []
        for _ in range(ho.CLOCK_SAVER_FRAME_STREAK + 1):
            ho._frame_check_worker(seen.append)
        self.assertTrue(seen[0])  # first fingerprint counts as a change
        self.assertFalse(any(seen[1:]))
        self.assertEqual(ho.hdmi_unchanged_streak(), ho.CLOCK_SAVER_FRAME_STREAK)
        self.assertTrue(ho.hdmi_clock_saver_due())

    def test_changed_frame_resets_streak(self) -> None:
        a = np.zeros((270, 480, 3), dtype=np.uint8)
        b = np.full((270, 480, 3), 200, dtype=np.uint8)
        frames = [a, a, a, b]
        ho._grab_frame = lambda: frames.pop(0)  # type: ignore[method-assign]
        seen: list = []
        for _ in range(4):
            ho._frame_check_worker(seen.append)
        self.assertEqual(seen, [True, False, False, True])
        self.assertEqual(ho.hdmi_unchanged_streak(), 0)
        self.assertTrue(ho.hdmi_last_frame_changed())

    def test_no_frame_reports_none(self) -> None:
        ho._grab_frame = lambda: None  # type: ignore[method-assign]
        seen: list = []
        ho._frame_check_worker(seen.append)
        self.assertEqual(seen, [None])
        self.assertEqual(ho.hdmi_unchanged_streak(), 0)


if __name__ == "__main__":
    unittest.main()
