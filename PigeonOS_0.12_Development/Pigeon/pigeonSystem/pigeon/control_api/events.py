"""Server-Sent Events fan-out. Each subscriber gets a small bounded queue."""

from __future__ import annotations

import itertools
import json
import queue
import threading

MAX_SUBSCRIBERS = 4  # Zero 2 W budget (see spec §8)


class EventHub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: list[queue.Queue] = []
        self._ids = itertools.count(1)

    def subscribe(self) -> queue.Queue | None:
        with self._lock:
            if len(self._subs) >= MAX_SUBSCRIBERS:
                return None
            q: queue.Queue = queue.Queue(maxsize=64)
            self._subs.append(q)
            return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)

    def publish(self, event: str, data: object) -> None:
        payload = format_event(event, data, next(self._ids))
        with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass  # slow client; it will resync on reconnect via snapshot


def format_event(event: str, data: object, event_id: int | None = None) -> bytes:
    lines = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return ("\n".join(lines) + "\n\n").encode("utf-8")
