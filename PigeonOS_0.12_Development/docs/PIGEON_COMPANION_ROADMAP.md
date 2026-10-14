# Pigeon companion app and Control API: roadmap

Status: draft v0.1 (2026-10-14). Nothing here is built yet. The full endpoint contract is in [control_api_v1.md](control_api_v1.md). This is the plan that lets Marquee and the iOS app start without reworking PigeonOS twice.

## 1. Product split

| | **Pigeon Clock** | **Pigeon Marquee** |
|---|---|---|
| Role | In-theater appliance | Outside-theater signage |
| Hardware | Self-contained, built-in screen | Headless, HDMI out to a customer screen |
| Visualizers | Yes | No |
| Companion app | Quality-of-life | **Required** (the only UI) |
| Candidate board | Pi 4/5 (today) | Pi Zero 2 W (to be validated) |

Both run the same PigeonOS codebase. They differ by a **device profile**, not a fork.

### Device profile (new concept)

A small, declared set of facts the device reports about itself:

```json
{
  "product": "clock",              // "clock" | "marquee"
  "capabilities": ["viz", "clock", "now_playing", "manual_search", "wifi", "pairing_player", "pairing_receiver", "rotary"],
  "has_local_ui": true,            // false = app is the only way to configure it
  "api_version": 1
}
```

The app builds its UI from `capabilities`, so a Marquee never shows visualizer settings and future products need no app changes. `device_capability_matrix.py` already exists in `pigeonSystem/`; check whether it can seed this before inventing a second mechanism.

## 2. What the codebase gives us today

Findings from reading `pigeonSystem/` (v0.12.11):

- **No control surface exists.** The only HTTP server is `pigeon_report_server.py`, a Mac-side developer tool. Nothing on the device listens for commands, and nothing advertises over mDNS.
- **Settings are a flat JSON state file** behind `pigeon/app_state.py` (`read_app_state`, `write_app_state`, atomic writes, location v2 model with per-location Wi-Fi, devices and slots). This is a good seam: an API can sit on it.
- **Manual search is already UI-free.** `pigeon/manual_search.py` has no UI imports (`suggest_now`, `set_entry`, `clear`, `current`). It is the easiest first endpoint and is the primary app use case.
- **Pairing is welded to Tk.** `core/pairing.py` drives dialogs, PIN modals and LED canvases and takes ~20 injected UI closures. Player/receiver pairing over an API needs the *state machine* (start, PIN required, PIN submitted, success/fail) pulled out from the dialogs first. This is the largest refactor.
- **Wi-Fi code exists** (`wifi_scan.py`, `wifi_connect.py`, NetworkManager/`nmcli` on Linux) and is usable headless.
- **Heavy dependencies** (`opencv-python`, `numpy`, `pyatv`, `numbers-parser`, `pymupdf`, Tk) are Pi 4/5 assumptions. A Zero 2 W (512 MB, quad A53) may not carry the full stack; Marquee likely needs a *lean runtime profile* (see Phase 3).
- Settings UI is built twice: main_settings/preferences widgets on-device and, soon, the app. Without a shared definition these will drift.

## 3. Architecture

```
 iOS app "Pigeon"  ──(LAN: mDNS + HTTPS/JSON + SSE)──▶  PigeonOS device(s)
        │                                                   │
        └── first-boot only: BLE or setup hotspot ──────────┘  (Wi-Fi provisioning)
```

### 3.1 Transport
- **Discovery:** mDNS/Bonjour service `_pigeon._tcp` with TXT records: `id`, `name`, `product`, `api`, `ver`. iOS: `NWBrowser`. Device: `avahi` or Python `zeroconf` (small, pure Python).
- **Control:** HTTP+JSON on the LAN, prefix `/api/v1`. Python stdlib `ThreadingHTTPServer` is enough and adds no dependency (the report server already uses it). Revisit only if SSE load demands it.
- **Live state:** Server-Sent Events at `/api/v1/events` (now playing, connection and pairing progress). Simpler than WebSockets on both ends.
- **Local-first:** no cloud, no account. The device is the source of truth.

### 3.2 Security (decide before shipping anything)
Anything on the LAN could otherwise rewrite Wi-Fi credentials or pairings.
- App claims a device through a **pairing code** shown on the Clock's screen, or printed/QR on the Marquee (and shown on its HDMI output at first boot). Result: a long-lived bearer token stored in the iOS Keychain.
- Unauthenticated endpoints: `GET /hello` (id, name, product, claimed?) only.
- Plain HTTP with tokens on a home LAN is a defensible v1 *if* the token never travels in a query string; HTTPS with a self-signed cert pinned at claim time is the better target. Flagged as an open decision.

### 3.3 Provisioning a headless device (the hard problem)
A Marquee with no screen UI and no Wi-Fi cannot be found by mDNS. Options:

| Option | Pros | Cons |
|---|---|---|
| **Setup hotspot** (device boots an AP `Pigeon-XXXX`; app joins via `NEHotspotConfiguration`, sends SSID/password, device reboots to client mode) | Works on every Pi with Wi-Fi, familiar | One-time network switch, AP mode handling in NetworkManager |
| **BLE provisioning** (GATT service for SSID/password) | Smooth, no network switch | Pi Zero 2 W has BLE, but BlueZ/GATT server is more code and more failure modes |
| **Ethernet only** | Trivial | Unacceptable as the product story |

Recommendation: **setup hotspot first** (simplest, no new hardware dependency). The Marquee shows its setup instructions and pairing code on the HDMI output, which makes the screen part of onboarding too.

### 3.4 One settings definition, three consumers
Introduce a **settings registry**: each configurable item declared once (`id`, type, range/options, label, group, capability required, restart needed?). The API serves it at `/api/v1/settings/schema`, the app renders from it, and the on-device UI can migrate onto it over time. This is what makes "the app touches anything configurable" tractable and keeps new settings from needing app releases.

## 4. API v1 sketch

All paths under `/api/v1`, bearer token unless noted.

| Area | Endpoints | Backed by |
|---|---|---|
| Identity | `GET /hello` (open), `POST /claim`, `GET /device`, `PATCH /device` (name) | new |
| Capabilities | `GET /capabilities` | device profile |
| Search (v1 priority) | `GET /search/suggest?q=`, `PUT /search/current`, `DELETE /search/current`, `GET /search/current` | `manual_search.py` |
| Clock / location | `GET/PATCH /clock`, `GET/POST/PATCH/DELETE /locations` | `app_state` location v2 |
| Room | `PUT /location/room` | location slots / `LOCATION_PRESET_ROOM_NAMES` |
| Wi-Fi | `GET /wifi/scan`, `GET /wifi`, `PUT /wifi` | `wifi_scan`, `wifi_connect` |
| Player pairing | `GET /discovery/players`, `POST /pairing/players` → `{session}`, `POST /pairing/{session}/pin`, `DELETE /players/{id}` | refactored `core/pairing.py` |
| Receiver pairing | same shape under `/receivers` | refactored `core/pairing.py` |
| Settings | `GET /settings/schema`, `GET/PATCH /settings` | settings registry |
| Visuals (later) | part of `/settings`, gated by `viz` capability | registry |
| Status | `GET /status`, `GET /events` (SSE) | now_playing, source_status |
| Maintenance | `POST /update/check`, `POST /restart` | `github_update`, `update_check` |

Rules: versioned, additive-only within v1; errors as `{code, message}`; long operations (scan, pairing) return a session id and report through SSE.

## 5. The iOS app, "Pigeon"

- **Native SwiftUI**, iOS 17+. Bonjour and `NEHotspotConfiguration` favour native over cross-platform.
- **Design language:** derive tokens (colors, type, spacing, corner radii) from PigeonOS (`pigeon/design.py`, `pigeonAssets/`, fonts in `pigeonAssets/fonts`) into a single `tokens.json` that both Python and Swift read. Do not re-draw by eye.
- **Information architecture:**
  1. **Search** is the first tab and the launch screen. One field, instant suggestions, tap a result and it goes to the selected device. Device switching is a compact chip above the field, not a navigation step.
  2. **Devices**: all Clocks and Marquees, with status; tap to configure (Wi-Fi, room, location/clock, players, receivers, visuals).
  3. **Add device**: discovery and first-run claim.
- **Multi-device:** the app keeps a local registry of devices (`id`, name, token, last IP). Search can target one device or several ("send to all in this room").
- **Offline/away:** devices are LAN-only, so the app shows last-known state and clear "not on this network" copy rather than errors.

## 6. Repository layout (proposed)

Keep one repo; add, do not move.

```
PigeonOS_0.12_Development/
  Pigeon/pigeonSystem/pigeon/
    control_api/        new: server, auth, routes, SSE, mDNS advertise
    profile.py          new: device profile + capabilities
    settings_registry.py  new
  PigeonApp/            new: Xcode project "Pigeon" (SwiftUI)
  docs/
    PIGEON_COMPANION_ROADMAP.md   this file
    control_api_v1.md             OpenAPI-style spec (Phase 0 output)
```

## 7. Phases

| Phase | Outcome | Notes |
|---|---|---|
| **0. Contract** | `control_api_v1.md` spec; device profile and capability list agreed; security decision made | No code risk. Unblocks app and device in parallel. |
| **1. Read-only + Search** | Device serves `/hello`, `/device`, `/status`, `/events`, `/search/*`; mDNS advertise; claim flow | Smallest slice that makes the app useful for its primary use case. Runs inside the existing app process on a thread, off by default behind a flag. |
| **2. App MVP** | Search-first app; discover, claim, search, set Wi-Fi/room/clock | Clock only; this proves the loop on hardware we have. |
| **3. Marquee runtime** | Lean profile (no viz/cv2 if possible), Zero 2 W benchmark, setup hotspot provisioning, HDMI onboarding screen | Gate: does the display pipeline hold 1080p posters on a Zero 2 W? Decide the board *here*, with data. |
| **4. Pairing over API** | Players and receivers paired from the app | Needs the `core/pairing.py` state-machine extraction. Biggest refactor; do it behind tests. |
| **5. Settings registry + visuals** | Whole settings surface in the app | Migrate on-device settings to the registry incrementally. |

## 8. Open decisions (need the owner)

1. **Pi Zero board:** Zero 2 W is the realistic floor (original Zero W is ARMv6 and will not run this stack). Confirm, or accept validating in Phase 3 first.
2. **Provisioning:** setup hotspot (recommended) vs BLE.
3. **Transport security:** token over HTTP on the LAN for v1, or self-signed HTTPS with pinning from day one.
4. **Branding in code:** keep the `pigeon` Python package and `PigeonOS` name; add `product` in the profile. Rename nothing now.
5. **Scope of "multiple Clocks per app":** per-device only for v1, or grouped actions (rooms, "all devices") from the start?
6. **Dev environment:** Xcode's license has not been accepted on this Mac (`sudo xcodebuild -license`). That also blocks `git` and any iOS build until done.

## 9. Not in scope here

Marquee-specific content/signage features (poster rotation, schedules, "other signage"). They need their own spec once the transport and provisioning above exist.
