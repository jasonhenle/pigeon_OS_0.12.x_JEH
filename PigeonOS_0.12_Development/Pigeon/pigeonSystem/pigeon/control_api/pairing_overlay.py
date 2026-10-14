"""Full-screen "enter this code in the Pigeon app" prompt, like the Apple TV PIN screen.

``render_pairing_image`` is pure PIL (testable without Tk). ``PairingOverlay`` is a
Tk label placed over the whole window; it polls ``get_code`` on the UI thread, so
it needs no cross-thread plumbing and never touches the render pipeline.
"""

from __future__ import annotations

from typing import Callable

from PIL import Image, ImageDraw, ImageFont

ACCENT_RGB = (78, 166, 247)  # #4EA6F7
POLL_MS = 250


def _font(path: str | None, size: int):
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _fonts() -> tuple[str | None, str | None]:
    digital = ui = None
    try:
        from pigeon.font_paths import resolve_digital7_font

        digital = resolve_digital7_font()
    except Exception:
        pass
    try:
        from pigeon.font_paths import resolve_ui_font_medium

        ui = resolve_ui_font_medium()
    except Exception:
        pass
    return digital, ui


def render_pairing_image(code: str, width: int, height: int) -> Image.Image:
    """Black screen, small heading, the code as large as fits, a hint line."""
    w, h = max(320, int(width)), max(200, int(height))
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    digital, ui = _fonts()

    heading = ImageFont.load_default() if ui is None else _font(ui, max(18, h // 22))
    hint = _font(ui, max(16, h // 30))
    text = " ".join(str(code))  # spaced digits read better from across a room

    # Grow the code until it fills ~80% of the width (cap at 38% of the height).
    size = max(40, h // 4)
    big = _font(digital or ui, size)
    for s in range(int(h * 0.38), 40, -4):
        f = _font(digital or ui, s)
        l, t, r, b = d.textbbox((0, 0), text, font=f)
        if r - l <= w * 0.8:
            big = f
            break

    def centered(s: str, font, y_center: float, fill) -> None:
        l, t, r, b = d.textbbox((0, 0), s, font=font)
        d.text(((w - (r - l)) / 2 - l, y_center - (b - t) / 2 - t), s, font=font, fill=fill)

    centered("ADD THIS PIGEON TO THE PIGEON APP", heading, h * 0.22, ACCENT_RGB)
    centered(text, big, h * 0.50, (255, 255, 255))
    centered("Enter this code on your phone.", hint, h * 0.76, (154, 154, 154))
    return img


class PairingOverlay:
    """Shows/hides the prompt as ``get_code()`` toggles between a code and ``""``."""

    def __init__(self, root, get_code: Callable[[], str]) -> None:
        import tkinter as tk

        self._root = root
        self._get_code = get_code
        self._label = tk.Label(root, bg="black", bd=0, highlightthickness=0)
        self._photo = None
        self._shown_key: tuple | None = None
        self._visible = False

    def start(self) -> None:
        self._tick()

    def _tick(self) -> None:
        try:
            code = self._get_code()
            if code:
                self._show(code)
            elif self._visible:
                self._hide()
        except Exception:
            pass
        try:
            self._root.after(POLL_MS, self._tick)
        except Exception:
            pass

    def _show(self, code: str) -> None:
        w = int(self._root.winfo_width() or 0) or 1280
        h = int(self._root.winfo_height() or 0) or 800
        key = (code, w, h)
        if key != self._shown_key:
            from PIL import ImageTk

            self._photo = ImageTk.PhotoImage(render_pairing_image(code, w, h))
            self._label.configure(image=self._photo)
            self._shown_key = key
        if not self._visible:
            self._label.place(x=0, y=0, relwidth=1, relheight=1)
            self._visible = True
        self._label.lift()

    def _hide(self) -> None:
        self._label.place_forget()
        self._visible = False
        self._shown_key = None
        self._photo = None
