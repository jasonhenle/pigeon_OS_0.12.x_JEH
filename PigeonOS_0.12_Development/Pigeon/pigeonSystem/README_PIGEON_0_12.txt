# PigeonOS 0.11

**Pigeon** is a fixed-resolution (800×480) “Now Playing” display app.  
The entry point is `pigeon_0_12.py` (named after the MAJOR_MINOR version; `pigeon_0_9.py` remains as a small compatibility shim for older updaters).

## What it does

- Opens an **800×480** window.
- Loads a scene MP4 and starts **paused**.
- **SPACEBAR** toggles play/pause.
- Loops back to the beginning when the video ends.
- While **playing**: brightness **100%**.
- While **paused**: brightness **30%**.
- Scales the video to **fill the Y axis** (400px tall), and **center-crops** any extra width (no stretching).

## Install

```bash
python3 -m pip install -r requirements.txt
```

## Layout

Typical app tree:

- **`pigeonSystem/`** — this app (`pigeon_0_12.py`, `pigeon/` package).
- **`pigeonAssets/`** — scenes, widgets, logos, and UI media.

Paths are resolved automatically from the script location plus Desktop / iCloud fallbacks. Override anytime with **`PIGEON_SCENE`**, **`PIGEON_POSTER_ART_DIR`**, **`PIGEON_REFORMATTED_POSTER_DIR`**.

## Run

Preferred (installer launchers):

```bash
./installer/run_pigeon_0_12.sh          # Linux / Pi
./installer/run_pigeon_0_12.command     # macOS
```

Or directly from `pigeonSystem/`:

```bash
python3 pigeon_0_12.py
```

If the default clip was renamed or moved, the app searches for `.mp4` / `.mov` files and picks the best filename match. Check Terminal for `default scene (discovered) → …`.

Or pass an explicit path:

```bash
python3 pigeon_0_12.py --scene "/path/to/your_scene.mp4"
```

Or set an environment variable:

```bash
export PIGEON_SCENE="/path/to/your_scene.mp4"
python3 pigeon_0_12.py
```

## Controls

- **SPACE**: play/pause toggle
- **ESC**: quit
