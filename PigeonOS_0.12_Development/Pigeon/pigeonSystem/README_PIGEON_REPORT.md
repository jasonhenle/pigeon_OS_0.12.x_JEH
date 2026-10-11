# Pigeon accuracy report

A developer tool for tuning TMDb accuracy. Every Pigeon (pi4, pi5, Mac) sends one
event per TMDb lookup to a small server on the Mac, which shows it live and keeps a
spreadsheet.

## Run it (Mac)

Double-click `installer/run_pigeon_report.command`, or:

    cd pigeonSystem && .venv/bin/python pigeon_report_server.py

It opens <http://localhost:8765>:

- **Live** – each Pigeon's current metadata, the TMDb query it built, the attempts it
  made, and TT / backdrop / poster thumbnails for the title it picked.
- **Gallery** – every title pulled, with the three TMDb thumbnails side by side.
- **Log** – the spreadsheet. Type in **Notes**; tick **Wrong** for a bad match
  (⌘⇧X on a Pigeon ticks it too).

## Files (`~/Pigeon/pigeonReport`, override with `PIGEON_REPORT_ROOT`)

| File | What |
| --- | --- |
| `pigeon_accuracy.csv` | The spreadsheet, rewritten on every change (hand this to Claude) |
| `pigeon_accuracy.numbers` | Written by **Export .numbers** (a snapshot; add notes on the web page) |
| `accuracy/events.jsonl` | Raw events, including every TMDb attempt |
| `accuracy/annotations.json` | Your notes and wrong-match flags |

## Pigeon side

`pigeon/accuracy_report.py` posts from a background thread; nothing blocks the UI.
If the Mac is unreachable, events wait in `~/.pigeon_0_6/accuracy_outbox.jsonl` and
are sent later.

- Server URL: `PIGEON_REPORT_URL`, else `~/.pigeon_0_6/report_url`, else
  `http://127.0.0.1:8765` on the Mac and `http://Jasons-MacBook-Air.local:8765` on a Pi.
  Set it to `off` to disable.
- Device name: `PIGEON_ID`, else `pi5` / `pi4` from the board model, else `Mac`.
