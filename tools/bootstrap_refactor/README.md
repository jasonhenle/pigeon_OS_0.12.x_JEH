# bootstrap() lift tooling (passes 2–3)

(The entry point was renamed `pigeon_0_9.py` -> `pigeon_0_12.py` in 0.11.38; the
notes below that say `pigeon_0_12.py` describe the same file under its old name.)

Dev-only scripts used to move nested helpers out of `bootstrap()` in
`pigeonSystem/pigeon_0_12.py` into `pigeon/core/`. Not shipped.

Run from `PigeonOS_0.12_Development/Pigeon/pigeonSystem` with Python 3.10+:

```bash
T=../../../tools/bootstrap_refactor
python3 $T/pass2.py pigeon_0_12.py /tmp/p2.json        # classify every remaining helper
python3 $T/transform.py . $T/plan.json /tmp/p2.json $T/new_module_docs.json
```

A helper is lifted only when all of these hold:

- no `nonlocal` / `global`, no decorators, no `**kwargs`, constant defaults only, no class defs;
- every name it closes over from `bootstrap()` is bound exactly once, unconditionally,
  at top level, before the helper's `def`, and is never written via `nonlocal`;
- every name it closes over from `main()` is bound the same way before `root.mainloop()`;
- every module global it reads is definitely bound at import and never rebound with `global`.

Module-level `import x` / `from x import y` names are imported directly in the core
module; everything else becomes a keyword-only parameter bound with `bind_deps` at the
old `def` site. `transform.py` asserts each moved function's AST equals the original
apart from the added keyword-only params (docstrings compared after `cleandoc`).

`plan.json` maps target module -> helper names; it must list exactly the helpers that
`pass2.py` marks safe.

## Pass 3: forward references

Helpers blocked only because they close over something bound *later* in `bootstrap()`
can be lifted if their `bind_deps()` call moves down to just after the last of those
names is bound. `pass3.py` checks that nothing can use the helper while its name is
unbound (scope-aware call graph, Tk registrations, event-loop pumps, running threads,
callbacks handed off early); see its docstring.

```bash
python3 $T/pass2.py pigeon_0_12.py /tmp/p2.json
python3 $T/pass3.py pigeon_0_12.py /tmp/p2.json /tmp/p3.json
python3 $T/transform.py . $T/plan3.json /tmp/p3.json $T/new_module_docs.json
```

## Checks after any pass

```bash
python3 $T/verify_order.py pigeon_0_12.py      # bootstrap() never reads a name before binding it
python3 -m pyflakes pigeon/core/*.py
HOME=$(mktemp -d) python3 $T/smoke_bootstrap.py   # runs main() + bootstrap() top level with a fake tkinter
```

`smoke_bootstrap.py` needs the desktop requirements (no display or real Tk). It should
end with `SMOKE: bootstrap returned` / `SMOKE: main returned 0`.

## Pass 4: holders for rebound state

Most remaining helpers were blocked because they share variables that
`bootstrap()` reassigns (via `nonlocal` or a second top-level binding).
`holderize.py` converts such a variable into a one-element holder list — the
same `x_holder[0]` pattern the codebase already uses — so the name is bound
once and helpers can take it as a dependency:

```bash
python3 $T/holderize.py pigeon_0_12.py skip_cache dev_phase active_tmdb_title_key active_tmdb_display_title
```

It rewrites `x` → `x[0]` only where the name resolves to `bootstrap()`'s
binding (scope-aware; shadowing locals are left alone), wraps the first
top-level binding in `[...]`, and drops `x` from `nonlocal` declarations.
Variables that were only bound twice by `x = None` / `if ...: x = Widget()`
were instead collapsed to a single conditional expression by hand
(`status_bar_widget`, `view_circles_widget`, `main_settings_widget`).
Then re-run pass 2 / pass 3 and `transform.py` with `plan4.json` / `plan4b.json`.

Known pre-existing quirk preserved on purpose: `_prefetch_pigeon_update_badge`,
`_remove_streaming_device_at` and `_remove_receiver_device_at` assign
`skip_cache = None` without `nonlocal`, so they never cleared the render cache.

## Pass 5

`skip_cache` was still treated as rebound because three functions assign a
*local* `skip_cache` (the quirk above), and one nested `nonlocal skip_cache`
pointed at such a local. Those locals are renamed `_stale_skip_cache`
(behaviour unchanged). Then `playback_overlay_widget` was bound once and
`command_entry_visible`, `scene_enabled`, `info_cluster_blits`,
`last_timecode_motion_mono` holderized; `plan5.json` / `plan5b.json` lift 24 helpers.

Check every holderize run is a pure rename:

```bash
cp pigeon_0_12.py /tmp/before.py
python3 $T/holderize.py pigeon_0_12.py NAME ...
python3 $T/holder_equiv.py /tmp/before.py pigeon_0_12.py NAME ...   # AST: IDENTICAL
```

Dead code noticed (never called, kept verbatim): `_remove_saved_receiver_device`,
`set_current_receiver_only`.

## Pass 6

- `main()`-owned blockers: two redundant `import threading` statements inside
  `main()` made `threading` a `main()` local (the module already imports it);
  they are removed. `_clock_saver_volume` / `_volume_lines` are bound once
  (null-object classes defined unconditionally). `cap` is holderized with
  `holderize.py --main`.
- Holderized in `bootstrap()`: `last_atv_interaction_mono`, `black_photo`,
  `status_bar_blits`, `frame_interval_ms`, `use_backdrop_scene`,
  `backdrop_master_bgr`, `backdrop_app_logo_letterbox_fit`, `tmdb_logo_patch_bgra`.
- `transform.py` now also compares nested docstrings after `cleandoc`
  (dedenting a helper legitimately re-indents docstrings of functions inside it).
- `plan6.json` / `plan6b.json` lift 21 helpers; new module `pigeon/core/pairing.py`.

Still blocked: the remaining helpers are mostly forward-reference cases that
`pass3.py` rejects (they can run before a name they use is bound), plus 9
recursive helpers. `_handle_main_settings_action` is blocked by the
`_stale_skip_cache` nonlocal until the skip_cache quirk is fixed for real.

## skip_cache fix (behaviour change)

`_prefetch_pigeon_update_badge`, its nested `finish_prefetch`,
`_remove_streaming_device_at` and `_remove_receiver_device_at` now clear the
real render cache (`skip_cache[0] = None`) instead of a throwaway local, so
the settings screen repaints after an update-badge prefetch or device removal.

## Pass 7: late binding for forward references

`pass3.py` refuses a helper when something could call it before the names it
uses are bound. For names that are *functions* bound later in `bootstrap()`
(including the helper itself, when it is recursive), nothing has to move:
`pass7.py` binds them at the original `def` site as
`X=_late(lambda: X, "X")` (`pigeon.core.binding.late`), which looks `X` up on
every call exactly like the closure did (and raises `NameError` if called
before `X` exists, as before). A helper qualifies only if each such `X` is bound
once by a `def` / `_bind_deps(...)` / `_core_*.X`, and the helper only calls it
or passes it as an argument.

```bash
python3 $T/pass2.py pigeon_0_12.py /tmp/p2.json
python3 $T/pass7.py pigeon_0_12.py /tmp/p2.json /tmp/p7.json
python3 $T/transform.py . $T/plan7.json /tmp/p7.json $T/new_module_docs.json
```

`plan7.json` lifts 40 helpers (39 via late binding + `_handle_main_settings_action`,
freed by the skip_cache fix), incl. `render`-adjacent code such as
`compose_display_from_source` and `_apple_tv_auto_poll_tick`.

Remaining blockers: forward references to *values* bound later (holders and
widgets such as `dev_phase`, `main_settings_widget`, `update_btn`), and more
rebound state (`brightness_*`, `last_frame`, `scaled_*`, `_atv_ix_*`, …).

## Pass 8: hoisting, the last shared state, and deeper smoke checks

- `hoist.py` moves side-effect-free initialisers (holders like `[None]`,
  literal dicts; only literals / module globals / pure constructors allowed)
  to the top of `bootstrap()`, so helpers defined earlier can depend on them.
  Proof: module and `main()` ASTs unchanged, `bootstrap()` has the same
  statements, only reordered; `verify_order.py` clean.
- Holderized 25 more: `last_frame`, `scaled_display`, `scaled_version`,
  `playing`, `brightness_*`, `saved_backdrop_*`, `tmdb_logo_app_fallback_active`,
  `_atv_ix_*`, idle-dim animation state, `playback_overlay_blits`,
  `clock_patch_bgra`, `last_device_interaction_mono`.
  `_clock_patch_sig` was already a list only mutated in place; its needless
  `nonlocal` was dropped instead.
- `pass7.py` also accepts callbacks placed in dict/list displays, and
  `nonlocal`s that refer to names bound inside the helper itself.
- `transform.py` imports names used only in annotations (`np`, `tk`).
- `SMOKE_TICKS=1 smoke_bootstrap.py` runs every callback `bootstrap()`
  schedules (render, polls, splash, playback tick) once; results are identical
  to the unrefactored `main`.

Plans: `plan8.json`, `plan8b.json`, `plan8c.json` (35 helpers, incl.
`render_once`, `spawn_tmdb_poster_fetch`, `_receiver_poll_tick`).

Left in `bootstrap()`: 9 helpers that read Tk widgets created after them
(`main_settings_widget`, `view_circles_widget`, `update_btn`,
`purge_image_media_btn`) or `scene_enabled`.

Removed: `last_device_interaction_mono` was written (receiver poll, and a lost
local write in `_update_atv_interaction_from_poll_metadata`) but never read.

## Pass 9: deferred holders -- bootstrap() has no nested helpers left

The last helpers read Tk objects created after them. Instead of reordering
startup, each such object gets a holder up front that is filled where the
object has always been created:

```bash
python3 $T/holderize.py pigeon_0_12.py main_settings_widget:main_settings_widget_holder \
    view_circles_widget:view_circles_widget_holder update_btn:update_btn_holder \
    purge_image_media_btn:purge_image_media_btn_holder
python3 $T/defer.py pigeon_0_12.py main_settings_widget_holder view_circles_widget_holder \
    update_btn_holder purge_image_media_btn_holder scene_enabled
```

`NAME:NEW` makes the holder's name say it is a holder; bind sites that ran
after construction pass the widget itself (`main_settings_widget=main_settings_widget_holder[0]`),
so already-lifted helpers are unchanged. `defer.py` turns `H = [expr]` into
`H[0] = expr` in place (same moment, same order) plus `H = [None]` at the top;
code that runs earlier sees `None` instead of a `NameError`.
`plan9.json` lifts the final 9 helpers.

Known pre-existing issue (not changed here): functions defined directly in
`main()` (`_note_zone3_volume_takeover`, `_clock_saver_volume_raw`,
`_clock_saver_receiver_off`) read `view_circles_widget`,
`receiver_overlay_state`, `receiver_standby_holder`, which only exist inside
`bootstrap()`; the `NameError` is swallowed, so those reads never succeed.

## Pass 10: helpers defined directly in main()

Same rules one scope up: the parent is `main()`, the grandparent the module.
`pass10.py` does the pass-2 analysis (plus pass-7 late binding for recursion)
for `main()`'s top-level `def`s; `transform.py --scope=main` moves them with a
4-space dedent and binds them where the `def` stood.

```bash
python3 $T/pass10.py pigeon_0_12.py /tmp/p10.json
python3 $T/transform.py . $T/plan10.json /tmp/p10.json $T/new_module_docs.json --scope=main
```

`plan10.json` lifts 15 helpers: kiosk / quit / Tk error reporter (new
`pigeon/core/app_shell.py`), the clock-saver volume + rasterize helpers
(`saver_state.py`), and the splash-reveal clock helpers (`startup.py`;
`_live_clock_until_compose` is recursive, so it is late-bound).

`pass10.py` also refuses a helper that is stored as an attribute of anything
but the Tk root: a `functools.partial` is not a descriptor, so
`tk.Widget.pack = _pack_patched` would stop receiving `self`.

Left in `main()` after pass 10: the three `tk.Widget` patches,
`_clock_saver_layers` (`**kwargs`) and `_try_remove_splash_overlay` -- see pass 11.

## Pass 11: main() has no top-level helpers left

- `hoist_main.py` moves `splash_photo` and the three `_splash_*_cache` dicts
  (literal initialisers) out of `if _PIGEON_EXT:` to just before
  `_try_remove_splash_overlay`. Nothing reads them at `main()`'s top level; all
  other readers are closures created later inside that block. The only change:
  the non-ext path now has four empty containers nobody reads, and the helper's
  `except NameError` guard can no longer fire (kept verbatim).
- `pass10.py` accepts `**kwargs` when every call passes explicit keywords and
  none is a dependency name; deps become keyword-only params placed *before*
  `**kwargs`, so `kwargs` sees the same keys.
- `pass10.py --method NAME` allows a helper stored on a class; `transform.py`
  then binds it with `bind_method_deps` (new in `pigeon.core.binding`), which
  returns a real function so `tk.Widget.pack = _pack_patched` still gets
  `self`. Deps must start with `_`; no Tk call in the app passes such a keyword.

```bash
python3 $T/hoist_main.py pigeon_0_12.py _try_remove_splash_overlay \
    splash_photo _splash_rgb_cache _splash_bgra_cache _splash_photo_cache
python3 $T/pass10.py pigeon_0_12.py /tmp/p11.json \
    --method _pack_patched --method _grid_patched --method _place_patched
python3 $T/transform.py . $T/plan11.json /tmp/p11.json $T/new_module_docs.json --scope=main
```

`plan11.json` lifts the last 5. `main()`'s only top-level `def` is now
`bootstrap`.

## Pass 12: functions inside main()'s `if` blocks

`pass12.py` handles `def`s that are direct statements of an `if` body at
`main()`'s top level; `transform.py --scope=main-if` replaces each in place (so
the name is still bound only on that path). "Bound before" means dominating:
bound by a direct statement of `main()` before the `if`, or of the same `if`
body before the `def`. Two additions:

- *settled* names: `splash_total_frames`, `_splash_fade_frames`,
  `splash_png_paths`, `splash_video_path` are computed by several assignments,
  but all of them come before the `def` and definitely bind the name on every
  path (`definitely_binds`), so the value at the `def` is the value every
  later call read;
- a forward *value* (`_splash_reveal_i` for `_splash_frame_keeps_live_clock`)
  moves the binding down to just after it, only if the helper's name is not
  read anywhere in `main()` before the new bind point.

```bash
python3 $T/pass12.py pigeon_0_12.py /tmp/p12.json
python3 $T/transform.py . $T/plan12.json /tmp/p12.json $T/new_module_docs.json --scope=main-if
```

`plan12.json` lifts all 14 into the new `pigeon/core/splash.py` (the clock
prewarm worker, frame decode / prebake workers, `splash_tick`,
`_bootstrap_after_splash`). `smoke_bootstrap.py` now finds `bootstrap` through
a `bind_deps` partial too.

(Correction, found in the 0.11.37 review: the "splash off / on" smoke runs
reported for passes 12-16 used a `PIGEON_NO_SPLASH` variable that Pigeon
never reads, so both took the splash path. The non-splash path is covered by
`tests/test_startup_trace.py`'s `no_ext` trace.)

Still inline in `main()`: the two null-object classes (`_NullClockSaverVolumeHold`,
`_NullVolumeLineReveal`) and `bootstrap()` itself, whose ~700 top-level
statements are the remaining work.

## Pass 13: bootstrap() split into 14 phases

At most cut points 100-225 names are live across the boundary, so phases
share a `BootContext` (`pigeon/core/boot/context.py`) instead of returning
tuples. `phases.py` moves each slice of `bootstrap()`'s statements verbatim
into `pigeon/core/boot/pNN_*.py` as `run(ctx)`: a prologue `x = ctx.x` for
what it reads, the statements, an epilogue `ctx.y = y` for what later phases
read. `bootstrap()` seeds the context with the `main()` locals and module
globals the phases use, then calls the 14 `run`s. Helpers and their
`_bind_deps` wiring are unchanged; the wiring now lives in the phases.

```bash
python3 $T/phases.py pigeon_0_12.py $T/plan13.json          # analyse: in/out per phase, errors
python3 $T/phases.py pigeon_0_12.py $T/plan13.json --write  # rewrite (asserts each phase's AST)
```

What it checks (see its docstring): prologue names definitely bound when the
phase starts, epilogue names definitely bound when it ends; no deferred code
(lambda, genexp) reads a name a later phase rebinds -- except names bound once
by a simple statement of a later phase and read here only from deferred code
(`_late(lambda: X, "X")`, `command=lambda: X()`): those become `ctx.X`, and
`ctx.X = X` is written right after X's binding, so the lookup still happens at
call time (and `BootContext` raises `NameError` for a missing name, like the
closure did). `except E as e` names are handler-local.

`tests/test_boot_phases.py` keeps the wiring honest after hand edits: every
prologue read was written by the seed or an earlier phase, phase modules only
read bound names, and `bootstrap()` calls the phases in order.

To move a statement between phases, edit it by hand and fix the prologue /
epilogue; the test tells you if a read now comes before its write. The pass
2-12 tools and `verify_order.py` assume the old single `bootstrap()` body and
no longer apply.

pigeon_0_12.py: 5,949 -> 1,788 lines (bootstrap() is 179, mostly the seed).

## Pass 14: dead code

Once bootstrap() was split, pyflakes could see 13 phase locals that were
bound and never read. Each was a side-effect-free binding (a literal,
`time.monotonic()`, a `_core_*` reference or a `_bind_deps(...)` over names /
lambdas), so the binding is removed. The extracted helpers behind 7 of them
were called from nowhere else and are removed too:
`_settings_bind_wheel_globals`, `_remove_saved_player_device`,
`_remove_saved_receiver_device` (settings_ui), `_design_rect_to_window`
(stage_render), `_vv_music_track_title` (now_playing),
`_read_tmdb_quality_counts` (tmdb_flow), `set_current_receiver_only`
(device_control). `_format_tmdb_match_quality_glance` and
`_device_row_matches_saved` keep their core functions (tests use them).

## Pass 15: prune to a fixpoint

`prune.py` repeats, until nothing changes: drop side-effect-free phase
bindings nobody reads (including `x = ctx.x` prologue reads left over from
pass 14), then drop `ctx.x = x` writes and bootstrap() seeds no phase reads.

```bash
python3 $T/prune.py pigeon_0_12.py
```

This round removed 8 phase bindings, and with them the old Tk settings
mouse-wheel handlers `_settings_mousewheel`, `_settings_is_under_scroll_surface`
and `_settings_wheel_target_should_ignore` (pigeon/core/settings_ui.py): the
functions that bound them to the wheel (`_settings_bind_wheel_globals`, pass 14)
were never called, so they could never run. pigeon_0_12.py also drops the 30
top-level imports it no longer uses (unconditional imports only; the
`tkinter.*` submodule imports stay, because importing them is what makes
`tk.messagebox` etc. available to other modules).

## Pass 16: main()'s setup as phases too

`phases.py --scope=main` phases `main()`'s statements *before* `def bootstrap`
into `pigeon/core/boot/m01_*.py` .. `m04_*.py` (window + kiosk, shell + splash
state, volume + reveal helpers, splash). `main()` seeds `_main_ctx`, runs them,
then reads back every name the rest of `main()` and `bootstrap()` use
(bootstrap()'s free variables, from symtable). bootstrap() and its phases are
unchanged.

```bash
python3 $T/phases.py pigeon_0_12.py $T/plan16.json --scope=main          # analyse
python3 $T/phases.py pigeon_0_12.py $T/plan16.json --scope=main --write  # rewrite
python3 -m pyflakes pigeon_0_12.py > /tmp/pf.txt; python3 $T/prune_imports.py pigeon_0_12.py /tmp/pf.txt
```

Additions for this scope:

- class statements (the null-object classes) are allowed; every outer name
  their bodies / methods use counts as a (deferred) read;
- names bound only on one path (`splash_tick` exists only when `_PIGEON_EXT`)
  are read and written back inside `try: ... except NameError: pass`, so they
  stay unbound on the other path exactly as before;
- `__file__` is seeded from pigeon_0_12.py, so the startup log still names the
  script, not the phase module.

`tests/test_boot_phases.py` checks both groups (`m*` seeded by `_main_ctx`,
`p*` by bootstrap()'s `ctx`). pigeon_0_12.py: 1,748 -> 1,191 lines.

## Review of 0.11.37 (no code moved)

See `docs/STARTUP_REVIEW_0.11.37.md` and `docs/PI_SMOKE_CHECKS.md`.
`tests/startup_trace_harness.py` records every Tk call startup makes (plus
two rounds of scheduled callbacks and every bound handler fired once);
`tests/test_startup_trace.py` traces four configurations from the current
code and from 0.11.34 (extracted from git, same machine) and compares them.
Use it, not `smoke_bootstrap.py`, to check any future startup change.
