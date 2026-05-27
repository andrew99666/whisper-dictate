"""Modern floating-pill indicator built on PySide6.

Visual:
  - The window itself is transparent (per-pixel alpha via WA_TranslucentBackground).
  - The pill is a child widget centered inside with a real Gaussian drop shadow
    (QGraphicsDropShadowEffect) — looks like it's floating on any background.
  - Pill body: near-opaque dark with a hairline highlight on top.
  - Smooth anti-aliased rounded corners (QPainter, no chroma keys).
  - Animated dot: red while recording with gentle alpha pulse, orange when processing.
  - System font (Segoe UI Variable on Win11).

Architecture:
  - Qt requires its event loop on the MAIN thread on Windows.
  - This module exposes a widget + a thin `Overlay` facade. `Overlay` does NOT
    create or run the QApplication — main.py does that. `set_state()` is
    thread-safe (marshals via QMetaObject.invokeMethod / QueuedConnection),
    so the pynput keyboard listener and pystray callbacks can call it freely.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import (
    Qt, QTimer, Slot, QMetaObject, Q_ARG, QRectF, QPointF,
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QBrush, QPen, QGuiApplication,
)
from PySide6.QtWidgets import QApplication, QWidget, QGraphicsDropShadowEffect


# --------------------------- design constants ---------------------------

# Outer window includes generous padding so the drop shadow can render without clipping.
_PADDING = 24

_PILL_W = 168
_PILL_H = 38

_WIDTH = _PILL_W + _PADDING * 2
_HEIGHT = _PILL_H + _PADDING * 2

_BOTTOM_MARGIN = 64  # bottom of pill, measured from screen bottom

_PILL_FILL = QColor(28, 28, 30, 235)      # nearly opaque, slight translucency
_PILL_STROKE = QColor(255, 255, 255, 26)   # thin highlight along the edge
_TEXT_COLOR = QColor(242, 242, 247)

_DOT_REC = (255, 69, 58)     # systemRed (Dark Mode)
_DOT_PROC = (255, 159, 10)   # systemOrange (Dark Mode)
_DOT_MUTED = (255, 69, 58)   # systemRed — same as recording but solid (no pulse)

_LABELS = {
    "recording":  "Recording",
    "processing": "Processing",
    "muted":      "Mic muted",
}


# --------------------------- pill child widget ---------------------------

class _PillWidget(QWidget):
    """The actual visual pill. Has a Gaussian drop shadow applied by its parent."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.resize(_PILL_W, _PILL_H)
        self._state = "idle"
        self._pulse = 1.0

    def set_state(self, state: str) -> None:
        self._state = state
        self.update()

    def set_pulse(self, value: float) -> None:
        self._pulse = value
        self.update()

    def paintEvent(self, ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.TextAntialiasing, True)

        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        radius = rect.height() / 2

        # Pill body
        p.setBrush(QBrush(_PILL_FILL))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rect, radius, radius)

        # Hairline highlight along the edge
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(_PILL_STROKE, 1))
        p.drawRoundedRect(rect, radius, radius)

        # Dot
        if self._state in _LABELS:
            if self._state == "muted":
                r, g, b = _DOT_MUTED
                alpha = 1.0
            elif self._state == "recording":
                r, g, b = _DOT_REC
                alpha = self._pulse  # pulse while recording
            else:  # processing
                r, g, b = _DOT_PROC
                alpha = 1.0
            dot = QColor(r, g, b, int(255 * alpha))
            p.setBrush(QBrush(dot))
            p.setPen(Qt.NoPen)
            dot_size = 9.0
            dot_x = 16.0
            dot_y = (self.height() - dot_size) / 2
            p.drawEllipse(QPointF(dot_x + dot_size / 2, dot_y + dot_size / 2),
                          dot_size / 2, dot_size / 2)

        # Text
        label = _LABELS.get(self._state, "")
        if label:
            p.setPen(_TEXT_COLOR)
            font = QFont("Segoe UI Variable", 10)
            font.setWeight(QFont.Medium)
            p.setFont(font)
            text_rect = self.rect().adjusted(34, 0, -14, 0)
            p.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, label)


# --------------------------- outer (transparent) overlay widget ---------------------------

class _OverlayWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.resize(_WIDTH, _HEIGHT)

        # Pill child centered inside the outer window (which has padding for the shadow).
        self._pill = _PillWidget(self)
        pill_x = (_WIDTH - _PILL_W) // 2
        pill_y = (_HEIGHT - _PILL_H) // 2
        self._pill.move(pill_x, pill_y)

        # Real Gaussian drop shadow — gives the pill visible elevation on any background.
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 160))
        self._pill.setGraphicsEffect(shadow)

        # Position the pill so it ends up centered horizontally, with the pill's bottom
        # at (screen_bottom - _BOTTOM_MARGIN). We have padding around the pill in the
        # outer window, so the window's bottom is _PADDING below the pill's bottom.
        screen = QGuiApplication.primaryScreen().geometry()
        x = screen.x() + (screen.width() - _WIDTH) // 2
        y = screen.y() + screen.height() - _HEIGHT - (_BOTTOM_MARGIN - _PADDING)
        self.move(x, y)

        self._state = "idle"
        self._pulse = 1.0
        self._pulse_step = -0.035

        self._timer = QTimer(self)
        self._timer.setInterval(40)  # ~25 fps
        self._timer.timeout.connect(self._tick)

    @Slot(str)
    def set_state_slot(self, state: str) -> None:
        if state == self._state:
            return
        self._state = state
        if state == "recording":
            self._pulse = 1.0
            self._pulse_step = -0.035
            if not self._timer.isActive():
                self._timer.start()
            self._pill.set_state(state)
            self.show()
        elif state in _LABELS:
            self._timer.stop()
            self._pulse = 1.0
            self._pill.set_pulse(1.0)
            self._pill.set_state(state)
            self.show()
        else:
            self._timer.stop()
            self.hide()
        self._pill.update()

    def _tick(self) -> None:
        self._pulse += self._pulse_step
        if self._pulse <= 0.55:
            self._pulse = 0.55
            self._pulse_step = -self._pulse_step
        elif self._pulse >= 1.0:
            self._pulse = 1.0
            self._pulse_step = -self._pulse_step
        self._pill.set_pulse(self._pulse)


# --------------------------- public facade ---------------------------

class Overlay:
    """Thread-safe facade. Construct AFTER QApplication exists, on the main thread."""

    def __init__(self) -> None:
        self._widget: Optional[_OverlayWidget] = _OverlayWidget()

    def set_state(self, state: str) -> None:
        """Safe to call from any thread."""
        if self._widget is None:
            return
        try:
            QMetaObject.invokeMethod(
                self._widget, "set_state_slot",
                Qt.QueuedConnection, Q_ARG(str, state),
            )
        except Exception:
            pass

    def stop(self) -> None:
        if self._widget is None:
            return
        try:
            QMetaObject.invokeMethod(self._widget, "close", Qt.QueuedConnection)
        except Exception:
            pass
