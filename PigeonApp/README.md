# Pigeon Remote (iOS companion app)

Controls Pigeon Clock and Pigeon Marquee devices over the Control API
(`../PigeonOS_0.12_Development/docs/control_api_v1.md`). SwiftUI, iOS 17+. Runs on iPhone and iPad.

    brew install xcodegen
    cd PigeonApp && xcodegen generate && open Pigeon.xcodeproj

The project file is generated from `project.yml`; don't edit `Pigeon.xcodeproj` by hand.

Try it against a Mac: start PigeonOS with `PIGEON_CONTROL_API=1`, read the code from
Settings > Pigeon (or `pigeon.control_api.pairing_code()`), then Devices > + in the app.

Implemented: discovery (Bonjour), claim with the on-screen code, device list/rename/remove,
live search and pin/clear via `/search/*`, SSE updates, and Pigeon Clock Settings on one page: rooms
(rename, reset one room), Sports (scores show / hide, followed teams, today's games) via `/sports*`, then
collapsible Display (brightness, layout), Theme, Clock and System (status, update, factory reset,
restart). Not yet: Wi-Fi.
