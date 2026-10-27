# Pigeon Remote (iOS companion app)

Controls Pigeon Clock and Pigeon Marquee devices over the Control API
(`../PigeonOS_0.12_Development/docs/control_api_v1.md`). SwiftUI, iOS 17+. Runs on iPhone and iPad.

    brew install xcodegen
    cd PigeonApp && xcodegen generate && open Pigeon.xcodeproj

The project file is generated from `project.yml`; don't edit `Pigeon.xcodeproj` by hand.

Try it against a Mac: start PigeonOS with `PIGEON_CONTROL_API=1`, read the code from
Settings > Pigeon (or `pigeon.control_api.pairing_code()`), then Devices > + in the app.

Implemented: discovery (Bonjour), claim with the on-screen code, device list/rename/remove,
live search and pin/clear via `/search/*`, SSE updates, rooms, brightness, and Pigeon Clock Settings in
the device's General / Theme / Clock menus (update, reset, restart included), and Sports (scores show /
hide, followed teams, today's games) via `/sports*`. Not yet: Wi-Fi.
