"""Dev harness: drive the FakeReceiver the way Pigeon's encoder path does.

    python3 -m pigeon.receiver.harness --demo      # scripted walkthrough
    python3 -m pigeon.receiver.harness             # interactive; type 'help'

Isolated from production: nothing in Pigeon imports this module.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from pigeon.receiver.base import ReceiverEvent, ReceiverState  # noqa: E402
from pigeon.receiver.control import apply_rotary_action  # noqa: E402
from pigeon.receiver.fake import FakeReceiver  # noqa: E402

HELP = """commands:
  state                      show what Pigeon sees / the receiver's truth
  connect | disconnect       Pigeon's session to the receiver
  rotate N                   encoder detents (+N up, -N down), like the knob
  mute | power on|standby | input <name>
  ext volume <dB> | ext standby | ext on | ext input <name> | ext mute on|off
  link down | link up        network drop / return
  latency <sec>              delay before our commands take effect
  quit"""


class Harness:
    def __init__(self, out=print) -> None:
        self.out = out
        self.rx = FakeReceiver()
        self.rx.start_auto_pump()
        self.rx.set_event_sink(lambda e: self.out(f"    · {e.kind:<10} {e.text}"))
        self.rx.add_state_listener(self._changed)

    def _changed(self, old: ReceiverState, new: ReceiverState) -> None:
        self.out(f"    ► Pigeon sees: {_fmt(new)}")

    def run(self, line: str) -> bool:
        w = line.split()
        if not w:
            return True
        c, a = w[0].lower(), w[1:]
        rx = self.rx
        if c == "quit":
            return False
        elif c == "help":
            self.out(HELP)
        elif c == "state":
            self.out(f"  pigeon: {_fmt(rx.cached_state())}\n  truth : {_fmt(rx.truth())}")
        elif c == "connect":
            rx.connect()
        elif c == "disconnect":
            rx.disconnect()
        elif c == "rotate" and a:
            n = int(a[0])
            wake = rx.cached_state().powered_on is False
            for _ in range(abs(n)):
                apply_rotary_action(rx, "volume_up" if n > 0 else "volume_down", wake=wake)
        elif c == "mute":
            apply_rotary_action(rx, "mute_toggle")
        elif c == "power" and a:
            rx.set_power(a[0].lower() == "on")
        elif c == "input" and a:
            rx.set_input(" ".join(a))
        elif c == "ext" and a:
            k = a[0].lower()
            if k == "volume":
                rx.simulate_volume(float(a[1]))
            elif k == "standby":
                rx.simulate_power(False)
            elif k == "on":
                rx.simulate_power(True)
            elif k == "input":
                rx.simulate_input(" ".join(a[1:]))
            elif k == "mute":
                rx.simulate_mute(a[1].lower() == "on")
            else:
                self.out("?")
        elif c == "link" and a:
            rx.simulate_link(a[0].lower() == "up")
        elif c == "latency" and a:
            rx.latency_s = float(a[0])
        else:
            self.out("? (type 'help')")
        time.sleep(0.05)
        return True


def _fmt(s: ReceiverState) -> str:
    if not s.connected:
        return "DISCONNECTED"
    pw = {None: "?", True: "on", False: "standby"}[s.powered_on]
    return f"power={pw} volume={s.volume_line or '?'} input={s.input_label or '?'}"


DEMO = [
    "connect", "state", "ext volume -35", "ext input Apple TV", "rotate 4", "rotate -2",
    "latency 0.3", "rotate 2", "state", "ext volume -20", "ext standby", "rotate 1",
    "ext on", "link down", "rotate 1", "link up", "connect", "state", "quit",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    h = Harness()
    if ap.parse_args().demo:
        for cmd in DEMO:
            print(f"> {cmd}")
            if not h.run(cmd):
                break
            if cmd.startswith("rotate 2") or cmd == "ext standby":
                time.sleep(0.5)
        return
    print(HELP)
    while True:
        try:
            if not h.run(input("> ")):
                break
        except (EOFError, KeyboardInterrupt):
            break


if __name__ == "__main__":
    main()
