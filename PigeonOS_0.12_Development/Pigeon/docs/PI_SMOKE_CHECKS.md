# Raspberry Pi smoke checks (startup refactor, 0.11.35+)

The automated tests run Pigeon under a fake Tk. They prove that startup makes
the same calls, in the same order, as 0.11.34. They cannot see real drawing,
timing, GPIO, serial, the receiver, the Apple TV or the HDMI capture card.
Run these checks on one Pi after any build that touches startup
(`pigeon/core/boot/`, `pigeon_0_12.py`), before updating the second Pi.

Takes about 20 minutes. Check the ☐ boxes; anything that fails, note the time
and grab the log (see "What to send back").

## Before you start

- ☐ Update the Pi (Settings → Pigeon → UPDATE) and note the old version.
  Confirm the new one on the Pigeon settings page (`PIGEON V 0.11.xx`).
- ☐ Open a second terminal (SSH) on the Pi and follow the log:
  `journalctl -u pigeon -f` (service), or `tail -f ~/.pigeon_0_6/pigeon.log`.
- ☐ Keep watching for `Traceback`, `Tk callback exception`, `NameError`,
  `not defined (not bound yet in bootstrap)` or `AttributeError`. Any of these
  is a failure.
- **Escape quits Pigeon.** It only closes the command bar if the bar is open.
  Don't use it to back out of menus.

## 1. Startup and splash

Restart Pigeon (`sudo systemctl restart pigeon`), or reboot for a true cold
start.

- ☐ The log starts with `pigeon: running script …/pigeon_0_12.py`. It names
  the script, not a `pigeon/core/boot/…` file.
- ☐ Kiosk: the window covers the whole screen, with no desktop bar or window
  frame. About a second in, the log shows `pigeon: kiosk WxH+0+0 screen=WxH`.
- ☐ The splash plays smoothly at full rate. No frozen last frame and no
  multi-second stall. This is the main thing the startup split could have
  disturbed.
- ☐ The first frames of the splash are over black. The clock only appears
  under the splash near the end, at the reveal frame, and never flashes in at
  the start.
- ☐ The splash lifts cleanly into the clock / landing screen, with no black
  flash in between. The log shows all three of these lines. Their order
  depends on whether setup or the splash finishes first:
  - `pigeon: splash overlay lifted +…s`
  - `pigeon: view1 first-render (… ms)`
  - `pigeon: view1 bootstrap-done +…s`
- ☐ Timing is about the same as the old version. Compare the `+…s` numbers
  with a 0.11.34 log if you have one. A difference well over a second is
  worth reporting.
- ☐ The clock ticks every second. The date and weather appear if configured.

## 2. Rendering

Needs the Apple TV (or Roku) on and paired.

- ☐ Start something playing. The now-playing screen appears within a poll or
  two, with the title, TMDb poster / backdrop / logo, progress bar and
  timecodes. The timecodes advance smoothly between polls.
- ☐ Pause. The paused row / pause saver appears. Resume: it goes away.
- ☐ Stop, or go back to the Apple TV home screen. After the idle delay Pigeon
  returns to the landing / clock saver.
- ☐ Digits 1–8 switch views, and each one draws. View 4 cycles its text pages;
  View 5 shows the grid overlay. Go back to View 1.
- ☐ Shift+2 forces the clock saver on; press it again to turn it off.
- ☐ Hold P+A+R together. The log prints `display PAR mode=…` and the picture
  aspect toggles. Toggle it back.
- ☐ Ctrl+Shift+S toggles the scene off and on.
- ☐ Ctrl+Shift+M toggles TMDb match mode. The log shows
  `TMDb title match: …`.
- ☐ Something with a streaming-app logo (e.g. HBO Max, Netflix) shows its
  badge / logo, not a blank.

## 3. Settings

- ☐ Tab opens settings; Tab again closes it. The rotary knob and arrow keys
  move the focus.
- ☐ Pigeon settings page:
  - The Wi-Fi, metadata and audio tiles have green/red dots that match
    reality.
  - The HDMI tile has **no** dot and is **not** greyed out. This is
  intended since 0.11.36.
  - The UPDATE tile shows a badge only when a newer version exists.
- ☐ 0 opens the metadata inspector. Page through player → hdmi → pigeon. The
  HDMI page's dot follows the capture card. Press 0 again to close.
- ☐ Devices → **Find device** opens the find-device dialog. Close it.
- ☐ Devices → **Advanced** opens the capability matrix. Close it.

  Both of these buttons look their handler up when pressed (the "deferred
  lookup" path in the review). A `NameError` here would show up in the log.
- ☐ Devices → **Updates** checks GitHub and reports "up to date" or offers the
  update. Don't apply it now.
- ☐ Location: rename the current location and save it, then rename it back.
  Don't test Delete or Reset. They wipe saved devices.
- ☐ Leave settings open and untouched. It closes itself after the idle
  timeout.

## 4. Volume and receiver (Denon)

- ☐ With the AVR on, the receiver volume / input shows on the now-playing
  screen and in the clock saver.
- ☐ Turn the volume knob (rotary on GPIO 23/24, push on 25):
  - the AVR volume changes;
  - the zone-3 volume widget takes over for about 7 s after the last turn,
    then goes back;
  - the clock saver's volume line appears and then fades.
- ☐ Push the volume knob to mute, then push again to unmute.
- ☐ Put the AVR in standby. Receiver lines disappear and the clock saver's
  volume line stays hidden. Turn the AVR back on: they come back.
- ☐ The play/pause button (GPIO 26) and Space toggle playback.
- ☐ The navigation knob (GPIO 17/27, push on 22) moves the focus in settings.
  The USB rotary works too, if you use one.

## 5. HDMI capture card

- ☐ Unplug HDMI from the capture card. After the next probe, the metadata
  inspector's HDMI page shows it gone. The settings tile doesn't change: no
  dot, by design.
- ☐ With an app in the foreground but no title from the player, now-playing
  stays up while there is HDMI signal.
- ☐ Leave a completely still picture (e.g. a paused menu) for more than 2
  minutes. The HDMI frame-change clock saver arms.

## 6. Soak

- ☐ Leave it playing for 30+ minutes, then idle for 30+ minutes. No
  exceptions in the log, no stutter, no growing lag.
- ☐ Optional: note the memory use at the start and end with
  `ps -o rss,cmd -C python3`.

## Pass / fail

- **Pass:** every box ticked and no exceptions in the log. Update the second
  Pi.
- **Fail:** roll that Pi back to the last good version and keep the log.
  Reinstall the tag (e.g. `v0.11.34`) with your usual installer, or check it
  out if the Pi runs from git.

## What to send back

- the version tested and which checks failed;
- the log from `pigeon: running script` through `bootstrap-done`;
- the first `Traceback` or `Tk callback exception` in full, and the ~20 lines
  before it: `journalctl -u pigeon --since "10 min ago"`.
