"""
Software-update flow for the settings screen.

Update check / apply buttons, the GitHub apply worker, the
periodic and automatic update ticks and the update button styling. Same contract as the
rest of ``settings_ui``: keyword-only dependencies bound with ``bind_deps``.

``pigeon.core.settings_ui`` re-exports every name here, so the boot phases that look the
functions up on ``settings_ui`` are unchanged.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox as messagebox

from pigeon.version import version_string


def _finish_update_check(result: object, *, _sync_update_button_style, update_check_state) -> None:
    update_check_state["checking"] = False
    update_check_state["last_check_mono"] = time.monotonic()
    try:
        from pigeon.update_check import UpdateCheckResult

        if isinstance(result, UpdateCheckResult):
            update_check_state["update_available"] = bool(result.update_available)
            update_check_state["remote_version"] = result.remote_version
            update_check_state["github_branch"] = result.github_branch
            update_check_state["error"] = result.error
    except Exception:
        update_check_state["update_available"] = False
    _sync_update_button_style()


def _linux_on_updates_button(*, _run_github_apply_worker, root, update_check_state) -> None:
    """Pi/Linux: skip Python version check; run curl|bash updater from GitHub."""
    if update_check_state.get("applying") or update_check_state.get("checking"):
        return
    local = version_string()
    github_target = "0.8 on GitHub main"
    try:
        from pigeon.update_check import fetch_remote_version_tuple, format_version_tuple

        remote_t, _, _, _ = fetch_remote_version_tuple(
            timeout_s=10.0, force=True
        )
        if remote_t is not None:
            github_target = format_version_tuple(remote_t)
    except Exception:
        pass
    if not messagebox.askyesno(
        "Updates",
        f"Download, install, and restart Pigeon from GitHub?\n\n"
        f"Installed: {local}\n"
        f"GitHub:    {github_target}\n\n"
        f"• Uses curl only (public repo — no GitHub token)\n"
        f"• App code and pigeonAssets are updated to 0.8\n"
        f"• Settings in ~/.pigeon_0_6 are kept\n"
        f"• Pigeon will restart as 0.8 when finished — no further steps\n\n"
        f"Continue?",
        parent=root,
    ):
        return
    _run_github_apply_worker(remote=github_target)


def _begin_apply_update(*, remote: str, branch: object, _run_github_apply_worker, root) -> None:
    local = version_string()
    if not messagebox.askyesno(
        "Install update",
        f"A newer Pigeon is on GitHub.\n\n"
        f"Installed: {local}\n"
        f"Latest:    {remote}\n\n"
        f"Download, install, and restart Pigeon now?\n\n"
        f"• App code and UI assets (pigeonAssets) will be updated from GitHub\n"
        f"• Settings stay in ~/.pigeon_0_6 (devices, TMDb key, pairing)\n"
        f"• Cached TMDb downloads in the app folder are kept\n"
        f"• Pigeon will restart automatically when finished — no further steps",
        parent=root,
    ):
        return

    _run_github_apply_worker(remote=str(remote), branch=str(branch) if branch else None)


def _check_for_updates(*, force: bool = False, _UPDATE_CHECK_INTERVAL_S, _finish_update_check, root, update_check_state) -> None:
    if update_check_state.get("checking"):
        return
    now = time.monotonic()
    last = float(update_check_state.get("last_check_mono") or 0.0)
    if not force and (now - last) < _UPDATE_CHECK_INTERVAL_S:
        return
    update_check_state["checking"] = True

    def worker() -> None:
        try:
            from pigeon.update_check import check_for_update

            # Periodic polls: one request against the last winning URL.
            result = check_for_update(quick=not force)
        except Exception as e:
            from pigeon.update_check import UpdateCheckResult

            result = UpdateCheckResult(
                local_version=version_string(),
                remote_version=None,
                update_available=False,
                error=str(e),
            )

        root.after(0, lambda r=result: _finish_update_check(r))

    threading.Thread(target=worker, daemon=True).start()


def _auto_update_tick(*, _AUTO_UPDATE_TICK_S, _AUTO_UPDATE_RETRY_S, _auto_update_busy, _auto_update_state_holder, _auto_update_playing, _run_github_apply_worker, root, update_check_state) -> None:
    """Auto-update (settings_pigeon option 5): install a known newer OS only
    while nothing is playing. One attempt per version per retry window."""
    try:
        from pigeon.widgets.options_settings import auto_update_enabled

        if (
            auto_update_enabled()
            and update_check_state.get("update_available")
            and not update_check_state.get("applying")
            and not update_check_state.get("checking")
            and not _auto_update_busy()
            and not _auto_update_playing()
        ):
            remote = str(update_check_state.get("remote_version") or "?")
            tried = _auto_update_state_holder
            now = time.monotonic()
            if tried.get("remote") != remote or (now - float(tried.get("at") or 0.0)) >= _AUTO_UPDATE_RETRY_S:
                tried["remote"] = remote
                tried["at"] = now
                branch = update_check_state.get("github_branch")
                _run_github_apply_worker(remote=remote, branch=str(branch) if branch else None, silent=True)
    except Exception:
        pass
    root.after(int(_AUTO_UPDATE_TICK_S * 1000), lambda: _auto_update_tick(
        _AUTO_UPDATE_TICK_S=_AUTO_UPDATE_TICK_S,
        _AUTO_UPDATE_RETRY_S=_AUTO_UPDATE_RETRY_S,
        _auto_update_busy=_auto_update_busy,
        _auto_update_state_holder=_auto_update_state_holder,
        _auto_update_playing=_auto_update_playing,
        _run_github_apply_worker=_run_github_apply_worker,
        root=root,
        update_check_state=update_check_state,
    ))


def _schedule_periodic_update_check(*, _UPDATE_CHECK_INTERVAL_S, _check_for_updates, _schedule_periodic_update_check, root) -> None:
    _check_for_updates(force=False)
    root.after(int(_UPDATE_CHECK_INTERVAL_S * 1000), _schedule_periodic_update_check)


def _sync_update_button_style(*, _match_neighbor_button_style, find_device_btn, update_btn_holder, update_check_state) -> None:
    _match_neighbor_button_style(update_btn_holder[0], ref=find_device_btn)
    if update_check_state.get("update_available"):
        update_btn_holder[0].configure(
            text="Updates ●",
            state=tk.NORMAL,
        )
    else:
        update_btn_holder[0].configure(
            text="Updates",
            state=tk.NORMAL,
        )


def _run_github_apply_worker(*, remote: str = "?", branch: str | None = None, silent: bool = False, _resolve_install_root_for_update, _sync_update_button_style, root, update_btn_holder, update_check_state) -> None:
    install_root = _resolve_install_root_for_update()
    # Auto-update runs unattended: no modal progress window, no error dialog.
    progress = None if silent else tk.Toplevel(root)
    status_var = tk.StringVar(value="Downloading from GitHub…")
    if progress is not None:
        progress.title("Updating Pigeon")
        progress.transient(root)
        progress.grab_set()
        tk.Label(progress, textvariable=status_var, padx=16, pady=16).pack()
    update_check_state["applying"] = True
    update_btn_holder[0].configure(state=tk.DISABLED)

    def worker() -> None:
        try:
            from pigeon.github_update import apply_github_update

            apply_branch = branch
            if apply_branch is None:
                cached = update_check_state.get("github_branch")
                if isinstance(cached, str) and cached.strip():
                    apply_branch = cached.strip()
            result = apply_github_update(install_root, branch=apply_branch)
        except Exception as e:
            from pigeon.github_update import ApplyUpdateResult

            result = ApplyUpdateResult(False, str(e))

        def finish_apply() -> None:
            update_check_state["applying"] = False
            update_btn_holder[0].configure(state=tk.NORMAL)
            if result.ok:
                status_var.set("Update complete — restarting Pigeon…")
                update_check_state["update_available"] = False
                if result.remote_version:
                    update_check_state["remote_version"] = result.remote_version
                else:
                    update_check_state["remote_version"] = remote
                _sync_update_button_style()

                def _restart_and_exit() -> None:
                    try:
                        if progress is not None:
                            progress.grab_release()
                            progress.destroy()
                    except tk.TclError:
                        pass
                    try:
                        from pigeon.github_update import restart_pigeon_after_update

                        restart_pigeon_after_update(
                            install_root, parent_pid=os.getpid()
                        )
                    except Exception:
                        pass
                    try:
                        root.destroy()
                    except tk.TclError:
                        pass
                    from pigeon.github_update import exit_code_after_update

                    os._exit(exit_code_after_update())

                root.after(400, _restart_and_exit)
                return

            try:
                if progress is not None:
                    progress.grab_release()
                    progress.destroy()
            except tk.TclError:
                pass
            if not silent:
                messagebox.showerror(
                    "Update failed",
                    result.message,
                    parent=root,
                )

        root.after(0, finish_apply)

    threading.Thread(target=worker, daemon=True).start()


def _on_updates_button(*, _begin_apply_update, _finish_update_check, _linux_on_updates_button, root, update_btn_holder, update_check_state) -> None:
    if sys.platform.startswith("linux"):
        _linux_on_updates_button()
        return
    if update_check_state.get("applying") or update_check_state.get("checking"):
        return

    progress = tk.Toplevel(root)
    progress.title("Updates")
    progress.transient(root)
    progress.grab_set()
    status_var = tk.StringVar(value="Checking GitHub for updates…")
    tk.Label(progress, textvariable=status_var, padx=16, pady=16).pack()
    update_check_state["checking"] = True
    update_btn_holder[0].configure(state=tk.DISABLED)

    def worker() -> None:
        try:
            from pigeon.update_check import check_for_update

            result = check_for_update(force=True)
        except Exception as e:
            from pigeon.update_check import UpdateCheckResult

            result = UpdateCheckResult(
                local_version=version_string(),
                remote_version=None,
                update_available=False,
                error=str(e),
            )

        def finish_check() -> None:
            update_check_state["checking"] = False
            _finish_update_check(result)
            try:
                progress.grab_release()
                progress.destroy()
            except tk.TclError:
                pass
            update_btn_holder[0].configure(state=tk.NORMAL)

            from pigeon.update_check import UpdateCheckResult

            if not isinstance(result, UpdateCheckResult):
                return
            if result.error:
                messagebox.showerror(
                    "Updates",
                    f"Could not check GitHub for updates.\n\n"
                    f"Installed: {result.local_version}\n\n"
                    f"{result.error}",
                    parent=root,
                )
                return
            if result.update_available:
                _begin_apply_update(
                    remote=str(result.remote_version or "?"),
                    branch=result.github_branch,
                )
                return
            remote = result.remote_version
            if remote:
                body = (
                    f"You are on the latest version GitHub reports.\n\n"
                    f"Installed: {result.local_version}\n"
                    f"GitHub:    {remote}"
                )
            else:
                body = (
                    f"No update information from GitHub.\n\n"
                    f"Installed: {result.local_version}\n\n"
                    f"If the repo is private, set PIGEON_UPDATE_GITHUB_TOKEN "
                    f"in the environment and try again."
                )
            messagebox.showinfo("Updates", body, parent=root)

        root.after(0, finish_check)

    threading.Thread(target=worker, daemon=True).start()
