"""First-run "Welcome to Pigeon" screen (see ``pigeon.setup_state``).

Two ways forward: scan the QR code with an iPhone to set up in the Pigeon app, or press
the knob on SET UP MANUALLY to carry on with the encoders. After a phone claims the
device from the QR code the screen switches to "Continue on your iPhone"; when the app
finishes (or the knob picks manual) it goes away.

``render_welcome_image`` is pure PIL + OpenCV (testable without Tk). ``WelcomeOverlay``
is a Tk label over the whole window, like ``control_api.pairing_overlay``: it polls on
the UI thread, so it needs no cross-thread plumbing and never touches the render pipeline.
While it is up it takes the knob (``handle_rotary_action``) and the keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ACCENT_RGB = (78, 166, 247)  # #4EA6F7, same as the pairing prompt
DIM_RGB = (154, 154, 154)
POLL_MS = 250
_KEYS = ("<Return>", "<KP_Enter>", "<space>", "<Left>", "<Right>", "<Up>", "<Down>", "<Escape>")

_active: "WelcomeOverlay | None" = None


@dataclass(frozen=True)
class WelcomeView:
    """Everything the screen shows; equal views render identical images."""

    state: str  # "welcome" or "app"
    url: str = ""  # QR payload; empty when the companion API is not running
    code: str = ""
    controller: str = ""


def qr_matrix(text: str) -> np.ndarray:
    """QR modules for ``text`` (uint8, 0 = dark, 255 = light) including the 4-module quiet zone."""
    params = cv2.QRCodeEncoder.Params()
    params.correction_level = cv2.QRCODE_ENCODER_CORRECT_LEVEL_M
    m = cv2.QRCodeEncoder.create(params).encode(text)
    if m is None or m.size == 0:
        raise ValueError("QR encode failed")
    return m


def _qr_image(text: str, max_px: int) -> Image.Image:
    m = qr_matrix(text)
    scale = max(1, int(max_px) // m.shape[0])
    big = np.kron(m, np.ones((scale, scale), dtype=np.uint8))
    return Image.fromarray(big).convert("RGB")


def _font(path: str | None, size: int):
    try:
        if path:
            return ImageFont.truetype(path, size)
    except Exception:
        pass
    return ImageFont.load_default()


def _fonts() -> tuple[str | None, str | None]:
    bold = medium = None
    try:
        from pigeon.font_paths import resolve_ui_font_bold

        bold = resolve_ui_font_bold()
    except Exception:
        pass
    try:
        from pigeon.font_paths import resolve_ui_font_medium

        medium = resolve_ui_font_medium()
    except Exception:
        pass
    return (str(bold) if bold else None), (str(medium) if medium else None)


def render_welcome_image(view: WelcomeView, width: int, height: int) -> Image.Image:
    w, h = max(480, int(width)), max(300, int(height))
    img = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    bold, medium = _fonts()
    title_f = _font(bold or medium, max(28, h // 13))
    body_f = _font(medium or bold, max(18, h // 28))
    small_f = _font(medium or bold, max(15, h // 36))
    pill_f = _font(bold or medium, max(18, h // 30))

    def text_w(s: str, font) -> int:
        l, _t, r, _b = d.textbbox((0, 0), s, font=font)
        return r - l

    def draw_at(s: str, font, x: float, y_center: float, fill) -> None:
        l, t, r, b = d.textbbox((0, 0), s, font=font)
        d.text((x - l, y_center - (b - t) / 2 - t), s, font=font, fill=fill)

    def centered(s: str, font, cx: float, y_center: float, fill) -> None:
        draw_at(s, font, cx - text_w(s, font) / 2, y_center, fill)

    def pill(label: str, cx: float, cy: float) -> None:
        pw = text_w(label, pill_f) + h // 8
        ph = max(48, h // 12)
        box = (cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2)
        d.rounded_rectangle(box, radius=ph // 2, outline=ACCENT_RGB, width=max(3, h // 220), fill=(0, 0, 0))
        centered(label, pill_f, cx, cy, (255, 255, 255))

    if view.state == "app":
        centered("CONTINUE ON YOUR IPHONE", title_f, w / 2, h * 0.30, ACCENT_RGB)
        who = view.controller.strip() or "Your iPhone"
        centered(f"{who} is setting up this Pigeon.", body_f, w / 2, h * 0.45, (255, 255, 255))
        centered("Follow the steps in the Pigeon app.", body_f, w / 2, h * 0.53, DIM_RGB)
        pill("SET UP MANUALLY INSTEAD", w / 2, h * 0.76)
        return img

    centered("WELCOME TO PIGEON", title_f, w / 2, h * 0.12, ACCENT_RGB)
    left_cx, right_x = w * 0.30, w * 0.56
    if view.url:
        qr_px = int(min(w * 0.36, h * 0.56))
        qr = _qr_image(view.url, qr_px)
        top = int(h * 0.22)
        img.paste(qr, (int(left_cx - qr.width / 2), top))
        below = top + qr.height + h * 0.05
        if view.code:
            centered(f"CODE  {' '.join(view.code)}", small_f, left_cx, below, DIM_RGB)
        lines = (
            ("Set up with your iPhone", (255, 255, 255), body_f),
            ("Scan the code with the Camera app.", DIM_RGB, small_f),
            ("It opens the Pigeon app, or the App", DIM_RGB, small_f),
            ("Store if you don't have it yet.", DIM_RGB, small_f),
        )
    else:
        lines = (
            ("Set up with your iPhone", (255, 255, 255), body_f),
            ("Restart Pigeon to show the code", DIM_RGB, small_f),
            ("for the Pigeon app.", DIM_RGB, small_f),
        )
    y = h * 0.30
    for s, fill, font in lines:
        draw_at(s, font, right_x, y, fill)
        y += h * (0.075 if font is body_f else 0.055)
    draw_at("Or set up here with the knob.", body_f, right_x, h * 0.62, (255, 255, 255))
    pill("SET UP MANUALLY", right_x + (text_w("SET UP MANUALLY", pill_f) + h // 8) / 2, h * 0.74)
    return img


def handle_rotary_action(action: str) -> bool:
    """Route a knob action to the Welcome screen when it is up. True means it was consumed."""
    ov = _active
    if ov is None or not ov.visible:
        return False
    if action == "activate":
        ov.choose_manual()
    return True  # turns and holds do nothing here, but must not reach the screens underneath


class WelcomeOverlay:
    """Shows the Welcome / "Continue on your iPhone" screen while setup is pending."""

    def __init__(
        self,
        root,
        *,
        get_view: Callable[[], WelcomeView | None],
        on_manual: Callable[[], object],
        ready: Callable[[], bool] = lambda: True,
    ) -> None:
        import tkinter as tk

        self._root = root
        self._get_view = get_view
        self._on_manual = on_manual
        self._ready = ready
        self._label = tk.Label(root, bg="black", bd=0, highlightthickness=0, takefocus=1)
        for seq in _KEYS:
            self._label.bind(seq, self._on_key)
        self._photo = None
        self._shown_key: tuple | None = None
        self.visible = False

    def start(self) -> None:
        global _active
        _active = self
        self._tick()

    def _tick(self) -> None:
        try:
            view = self._get_view() if self._ready() else None
            if view is not None:
                self._show(view)
            elif self.visible:
                self._hide()
        except Exception:
            pass
        try:
            self._root.after(POLL_MS, self._tick)
        except Exception:
            pass

    def _on_key(self, event) -> str:
        if getattr(event, "keysym", "") in ("Return", "KP_Enter", "space"):
            self.choose_manual()
        return "break"

    def choose_manual(self) -> None:
        self._hide()
        try:
            self._on_manual()
        except Exception:
            pass

    def _show(self, view: WelcomeView) -> None:
        w = int(self._root.winfo_width() or 0) or 1280
        h = int(self._root.winfo_height() or 0) or 800
        key = (view, w, h)
        if key != self._shown_key:
            from PIL import ImageTk

            self._photo = ImageTk.PhotoImage(render_welcome_image(view, w, h))
            self._label.configure(image=self._photo)
            self._shown_key = key
        if not self.visible:
            self._label.place(x=0, y=0, relwidth=1, relheight=1)
            self.visible = True
        self._label.lift()
        try:
            if self._root.focus_get() is not self._label:
                self._label.focus_set()
        except Exception:
            pass

    def _hide(self) -> None:
        self._label.place_forget()
        self.visible = False
        self._shown_key = None
        self._photo = None
