"""One failed or hung Apple TV poll must never end metadata polling for good."""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from unittest import mock


class _Root:
    """Collects ``after`` callbacks; ``drain`` runs them like Tk's loop would."""

    def __init__(self) -> None:
        self.queued: list[tuple[int, object]] = []

    def after(self, ms, fn, *a):
        self.queued.append((ms, (lambda fn=fn, a=a: fn(*a))))

    def drain(self) -> None:
        """Run zero-delay callbacks only; timed ones (the next poll) stay queued."""
        ready = [q for q in self.queued if q[0] == 0]
        self.queued = [q for q in self.queued if q[0] != 0]
        for _ms, fn in ready:
            fn()


def _tick_kwargs(root, state, fetch_exc=None):
    from pigeon.core import device_control as dc

    kw = {}
    for name in dc._apple_tv_auto_poll_tick.__code__.co_varnames[
        : dc._apple_tv_auto_poll_tick.__code__.co_kwonlyargcount
    ]:
        kw[name] = mock.MagicMock()
    kw.update(
        APPLE_TV_FAIL_POLL_MAX_MS=30000,
        APPLE_TV_IDLE_POLL_MS=9000,
        APPLE_TV_POLL_MS=3000,
        _PIGEON_EXT=True,
        _apple_tv_scan_timeout_s=lambda: 1,
        _idle_audio_meter_active=lambda: False,
        apple_tv_auto_state=state,
        apple_tv_busy={"active": False},
        apple_tv_dashboard_track={},
        current_apple_tv={"identifier": "id", "address": "1.2.3.4"},
        root=root,
        streaming_slot_holder=[None],
        resolve_metadata_tmdb_query=None,
    )
    return kw


class AppleTvPollRecovery(unittest.TestCase):
    def test_finish_failure_still_reschedules(self):
        from pigeon.core import device_control as dc

        root, state = _Root(), {}
        kw = _tick_kwargs(root, state)
        kw["_atv_metadata_is_content_idle"] = mock.MagicMock(return_value=False)
        kw["_content_key_from_metadata"] = mock.MagicMock(side_effect=RuntimeError("boom"))
        tick = lambda: dc._apple_tv_auto_poll_tick(**kw)  # noqa: E731
        kw["_apple_tv_auto_poll_tick"] = tick
        md = {"query": "Show", "title": "Show", "device_state": "Playing"}
        with mock.patch(
            "pigeon.apple_tv_now_playing.fetch_now_playing_info_for_device",
            return_value=(True, "ok", md),
        ):
            tick()
            for _ in range(300):
                root.drain()
                if any(ms > 0 for ms, _fn in root.queued):
                    break
                time.sleep(0.01)
        self.assertFalse(state.get("running"))
        self.assertTrue(any(ms > 0 for ms, _fn in root.queued), root.queued)

    def test_stalled_worker_is_abandoned(self):
        from pigeon.core import device_control as dc

        root = _Root()
        state = {"running": True, "running_since": time.monotonic() - 1000, "poll_gen": 4}
        kw = _tick_kwargs(root, state)
        kw["_atv_metadata_is_content_idle"] = mock.MagicMock(return_value=True)
        with mock.patch(
            "pigeon.apple_tv_now_playing.fetch_now_playing_info_for_device",
            return_value=(False, "no", None),
        ):
            dc._apple_tv_auto_poll_tick(**kw)
        self.assertEqual(state["poll_gen"], 5)

    def test_hung_fetch_times_out(self):
        from pigeon import apple_tv_now_playing as m

        async def hang(**_kw):
            await asyncio.sleep(60)

        with mock.patch.object(m, "_FETCH_NOW_PLAYING_TIMEOUT_S", 0.2), mock.patch.object(
            m, "_async_fetch_now_playing_info_for_device", hang
        ), mock.patch.object(m, "_ensure_pyatv"):
            ok, msg, md = m.fetch_now_playing_info_for_device(
                device_identifier="a", device_address="b"
            )
        self.assertFalse(ok)
        self.assertIn("timed out", msg)
        self.assertIsNone(md)


if __name__ == "__main__":
    unittest.main()
