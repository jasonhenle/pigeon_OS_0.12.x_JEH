# Startup refactor review — v0.11.37

Scope: the four `main()` phases (`pigeon/core/boot/m01`–`m04`) and fourteen
`bootstrap()` phases (`p01`–`p14`) introduced in passes 13 and 16, compared
against **0.11.34** (commit `30b2be9`, the last version with a single
`bootstrap()`). Focus: shared state, deferred callbacks, Tk `after()`
scheduling. Line numbers are for the `review/v0.11.37-startup` branch.

## Verdict

No behavioural regression found. Under a fake `tkinter`, 0.11.37 performs
the **same Tk calls in the same order with the same arguments** as 0.11.34 in
four startup configurations. That covers every widget construction,
`pack` / `place` / `configure` call, `bind` / `bind_all` / `bind_class` /
`protocol` call, `after()` delay and callback, and main-thread thread start.
The run then goes on through two rounds of the scheduled callbacks and fires
every bound handler once. The only differences are values that also vary
between two runs of 0.11.34 itself (see "Noise").

This is now a test, `tests/test_startup_trace.py`. It extracts 0.11.34 from
git into a temporary folder and traces both versions **on the same machine**,
so differences between the VM, a Mac and a Pi (GPIO, pyatv, fonts) cancel out.

| Configuration | What it exercises |
|---|---|
| `default` | normal startup: extensions loaded, so the splash path |
| `no_ext` | `_PIGEON_EXT = False` (optional imports failed): no splash, `root.after(1, bootstrap)` |
| `kiosk` | Pi kiosk mode (window-manager calls recorded, not run) |
| `devices` | saved Apple TV + Denon receiver, polls running |

Each run also goes through 2 rounds of scheduled callbacks and fires 96 bound
handlers: Tab, digits 0–8, arrows, Space, Escape, F9/F10, the P+A+R chord,
TMDb hotkeys, settings buttons, and so on. No handler raised in either
version.

**Correction to earlier pass notes.** Passes 12–16 reported smoke runs
"identical with the splash off and on". The smoke script's
`PIGEON_NO_SPLASH` variable is not read anywhere in Pigeon, so both of those
runs took the splash path. The path without the splash was first compared in
this review (`no_ext`), and it matches 0.11.34. `smoke_bootstrap.py` and the
tooling README now say so.

What the fake Tk cannot show — real drawing, real timing, GPIO, serial,
network devices, HDMI capture — is covered by the manual checks in
`docs/PI_SMOKE_CHECKS.md`.

## How shared state works (what was traced)

- `main()` seeds `_main_ctx` (`pigeon_0_11.py:893`) and runs `m01`–`m04`
  (`:930–933`). Then it reads back every name the rest of `main()` and
  `bootstrap()` use (`:935–981`).
- `bootstrap()` seeds its own `ctx` (`pigeon_0_11.py:987`) and runs `p01`–`p14`
  in order (`:1149–1162`).
- Each phase starts with `x = ctx.x` for its inputs, runs its original
  statements verbatim (AST-checked when generated), and ends with `ctx.y = y`
  for anything later phases read.
- Tk scheduling (`pigeon_0_11.py:1164–1186`) is unchanged. With the splash
  path, `splash_tick`, `_live_clock_until_compose` and
  `_bootstrap_after_splash` are queued with `after_idle`. Without it,
  `root.after(1, bootstrap)` runs. Then `mainloop()`.

## Risks, with references

### R1 — Deferred lookups through `ctx` (low; now test-guarded)

64 lambdas across 9 `p*` phases read a function that a *later* phase binds, as
`ctx.X` instead of a closure variable. Two forms:

- the pass-7 form, e.g.
  `_late(lambda: ctx._playback_progress_fraction_for_bar, …)` in
  `p03_settings_scaffold.py:149`, written by `p10_devices_logic.py:642`;
- plain callbacks, e.g. `command=lambda: ctx._open_find_device_dialog()` in
  `p05_devices_panel.py:136`.

They work because the binding phase writes `ctx.X = X` right after binding
(`p10_devices_logic.py:534` for the example). If a hand edit drops that write,
the button raises `NameError` when pressed, and Tk's error reporter logs it
(`pigeon/core/app_shell.py`). Startup itself would not fail.

**Guard added:** `test_every_ctx_read_has_a_writer` fails if any `ctx.X` read
anywhere in a phase (lambdas included) has no seed or phase that writes it.

### R2 — Stale closures after hand edits (low; now test-guarded)

A lambda in phase *k* closes over phase *k*'s local variable. In the original
single function, a later rebinding of that name was visible to the lambda. In
the split version it is not. The generator refused such cases, but nothing
stopped a later hand edit from introducing one.

**Guard added:** `test_deferred_reads_never_see_a_later_rebinding` fails if
deferred code in a phase reads a name that a later phase binds, ignoring the
`x = ctx.x` input lines. Checked by mutation: it catches an injected stale
lambda.

### R3 — Values copied when `main()` / `bootstrap()` start (low)

Module globals the phases read are copied into the seeds at
`pigeon_0_11.py:893` and `:987`. A global rebound after that point would not
reach the phases. Today the only `global` statement rebinds
`_TK_RGB_SCRATCH`, which is not seeded.

**Guard added:** `test_seeded_module_globals_are_never_rebound`.

### R4 — `splash_tick` exists only on the splash path (low; test-guarded)

`splash_tick` is bound only when `_PIGEON_EXT` is true, so it is written back
and read back inside `try … except NameError`:

- `m04_splash.py:440–443`
- `pigeon_0_11.py:976–979`

On the other path it stays unbound, as before. Its only reader is
`root.after_idle(splash_tick)` inside the matching `if _PIGEON_EXT:`
(`pigeon_0_11.py:1176`). The `no_ext` trace confirms the non-splash path
matches 0.11.34.

**Guard added:** `test_only_expected_names_are_path_dependent` pins the set of
such names to `{"splash_tick"}`, so a new one is a deliberate decision.

### R5 — `BootContext` and Python probes (fixed)

`BootContext.__getattr__` (`pigeon/core/boot/context.py:18`) raised
`NameError` for every missing name, including dunder probes. So
`copy.copy(ctx)`, `copy.deepcopy(ctx)` and `pickle` raised `NameError`.
Nothing in Pigeon does that today, but a debugger or a future helper could.

**Fixed:** missing `__dunder__` names now raise `AttributeError`. Plain names
still raise `NameError`, which matches the original closure behaviour. As a
result, `hasattr(ctx, "x")` still raises; use `"x" in vars(ctx)`.
`test_context_supports_copy_and_pickle` covers this.

### R6 — Tk calls from worker threads (pre-existing, unchanged)

Several worker threads schedule UI work with `root.after(0, …)` from outside
the Tk thread:

- `pigeon/core/device_control.py:557`, `:637`, `:1844` (`apply`)
- `pigeon/core/pairing.py:455` (`finish_scan`), `:975` (`apply_leds`)

This relies on a threaded Tcl build, which Raspberry Pi OS and macOS use. It
behaves the same in 0.11.34 and 0.11.37. These calls land in a different
position from run to run, so the trace test lists them separately. It is not a
regression, but it is the most likely source of an intermittent
`RuntimeError: main thread is not in main loop` if Tcl is ever unthreaded.

### R7 — Timing (info)

The phases add about 18 function calls and a few hundred attribute reads to
startup, which is negligible next to the ~150 ms first render.
`_playback_ui_tick` computes its next delay from elapsed time
(`pigeon/core/now_playing.py:1330`). Its delay differs by a few ms between any
two runs.

### R8 — Import order (checked, no issue)

The phase modules are imported at `pigeon_0_11.py:63–81`, earlier than some
modules used to be (e.g. `pigeon.linux_kiosk`, `pigeon.media_folders`,
`pigeon.tmdb_tt_contrast`). None of them does anything at import beyond
definitions. `sys.path` is set up before them (`:48–50`).

`pigeon/core/stage_render.py:25` imports `DisplayView` / `SceneFit` from
`pigeon_0_11` only under `TYPE_CHECKING`, so there is no runtime circular
import.

### R9 — Troubleshooting (info)

Tracebacks from startup now point into `pigeon/core/boot/m*.py` / `p*.py`
instead of `pigeon_0_11.py`. The log line
`pigeon: running script …/pigeon_0_11.py` is unchanged: `__file__` is seeded
from `pigeon_0_11.py`.

## Intentional changes since 0.11.34

These are not regressions. Testers should expect them.

- **0.11.36:** the HDMI tile on the Pigeon settings page has no status dot and
  is no longer greyed out without a signal.
- **0.11.36:** the old Tk settings mouse-wheel handlers were removed. They were
  never bound, so wheel behaviour is unchanged.
- **0.11.35–0.11.36:** 21 unused startup bindings and 10 dead helpers were
  removed (passes 14–15).

## Noise (varies between two runs of the same version)

- the version string;
- the `_playback_ui_tick` delay;
- anything worker threads do: threads they start, and `after()` callbacks they
  schedule (a finished scan, receiver poll or LED refresh).

The harness lists these separately and does not run them.

## Tests added

- `tests/startup_trace_harness.py`, `tests/test_startup_trace.py`: four
  configurations, each traced from the current code and from 0.11.34
  (extracted from git), then compared. Takes about 6 s.
  - It is skipped when git history isn't available, e.g. an installed copy.
  - For an intended startup change, move the baseline with
    `PIGEON_TRACE_BASELINE=<commit>`, and update `BASELINE` in the test when
    the change lands.
- `tests/test_boot_phases.py`, `BootPhaseInvariantTests`:
  - every `ctx` read has a writer;
  - no deferred read sees a later rebinding;
  - `ctx` is only the phase parameter;
  - seeded globals are never rebound;
  - the set of path-dependent names is pinned;
  - `BootContext` works with copy and pickle.
- Mutation checks run during the review, all caught:
  - swapping `p11` and `p12`: trace and order tests fail;
  - an injected stale lambda: the deferred-read test fails;
  - a `ctx` read with no writer: the ctx-writer test fails.
