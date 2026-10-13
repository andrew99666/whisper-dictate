"""Click-through dictation status; painting and telemetry polling stay on Qt."""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Slot, QMetaObject, Q_ARG, QRectF, QPointF
from PySide6.QtGui import QPainter, QColor, QFont, QPen, QGuiApplication, QCursor
from PySide6.QtWidgets import QWidget, QGraphicsDropShadowEffect

_PADDING = 24
_PILL_W = 284
_PILL_H = 54
_WIDTH = _PILL_W + _PADDING * 2
_HEIGHT = _PILL_H + _PADDING * 2
_BOTTOM_MARGIN = 28

_FILL = QColor(22, 24, 27, 250)
_TEXT = QColor(244, 245, 247)
_SECONDARY = QColor(153, 160, 170)
_RECORDING = QColor(255, 112, 116)
_PROCESSING = QColor(107, 222, 192)
_MUTED = QColor(255, 188, 111)
_LABELS = {"recording": "Recording", "processing": "Processing", "muted": "Mic muted"}


def _font(size: int, weight=QFont.Medium) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe UI Variable", "Segoe UI", "Arial"])
    font.setPixelSize(size)
    font.setWeight(weight)
    return font


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


class _PillWidget(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedSize(_PILL_W, _PILL_H)
        self._state = "idle"
        self._elapsed = 0.0
        self._levels = deque([0.0] * 9, maxlen=9)

    def set_state(self, state: str) -> None:
        self._state = state
        self._elapsed = 0.0
        self._levels = deque([0.0] * 9, maxlen=9)
        self.update()

    def set_frame(self, elapsed: float, level: float = 0.0) -> None:
        self._elapsed = elapsed
        # This display mapping never modifies the captured audio.
        strength = max(0.0, min(1.0, (level - 0.001) / 0.035))
        self._levels.append(math.sqrt(strength))
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        body = QRectF(0.5, 0.5, _PILL_W - 1, _PILL_H - 1)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1))
        p.setBrush(_FILL)
        p.drawRoundedRect(body, 27, 27)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 8), 1))
        p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 26, 26)

        if self._state not in _LABELS:
            return
        accent = {"recording": _RECORDING, "processing": _PROCESSING,
                  "muted": _MUTED}[self._state]
        center = QPointF(27, 27)
        if self._state == "recording":
            p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), 55), 1))
            p.drawEllipse(center, 9, 9)
            p.setPen(Qt.NoPen)
            p.setBrush(accent)
            p.drawEllipse(center, 4, 4)
        elif self._state == "processing":
            p.setPen(QPen(QColor(107, 222, 192, 35), 2))
            p.drawEllipse(center, 7, 7)
            p.setPen(QPen(accent, 2, Qt.SolidLine, Qt.RoundCap))
            angle = int(-self._elapsed * 260 * 16)
            p.drawArc(QRectF(20, 20, 14, 14), angle, 100 * 16)
        else:
            p.setPen(QPen(accent, 1.8, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(center, 7, 7)
            p.drawLine(QPointF(22, 32), QPointF(32, 22))

        p.setFont(_font(13, QFont.DemiBold))
        p.setPen(_TEXT)
        p.drawText(QRectF(45, 0, 99, _PILL_H), Qt.AlignVCenter | Qt.AlignLeft,
                   _LABELS[self._state])
        p.setPen(QPen(QColor(255, 255, 255, 20), 1))
        p.drawLine(QPointF(147, 18), QPointF(147, 36))

        if self._state == "recording":
            p.setPen(Qt.NoPen)
            for index, level in enumerate(self._levels):
                height = 3 + level * 22
                color = QColor(accent)
                color.setAlpha(100 + int(level * 155))
                p.setBrush(color)
                p.drawRoundedRect(QRectF(164 + index * 6, 27 - height / 2, 3, height), 1.5, 1.5)
            p.setFont(_font(12))
            p.setPen(_SECONDARY)
            # Bound the clock track even for hours-long dictations.
            clock_rect = QRectF(220, 0, 49, _PILL_H)
            text = _clock(self._elapsed)
            while p.fontMetrics().horizontalAdvance(text) > clock_rect.width() and p.font().pixelSize() > 8:
                font = p.font()
                font.setPixelSize(font.pixelSize() - 1)
                p.setFont(font)
            p.drawText(clock_rect, Qt.AlignVCenter | Qt.AlignRight, text)
        elif self._state == "processing":
            p.setPen(Qt.NoPen)
            # Indeterminate motion, not a fabricated completion percentage.
            for index in range(15):
                wave = (1 + math.cos(index * 0.45 - self._elapsed * 5)) / 2
                color = QColor(accent)
                color.setAlpha(45 + int(wave * 180))
                height = 3 + wave * 10
                p.setBrush(color)
                p.drawRoundedRect(QRectF(165 + index * 6, 27 - height / 2, 3, height), 1.5, 1.5)
        else:
            p.setPen(QPen(QColor(153, 160, 170, 110), 2, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(166, 27), QPointF(263, 27))


class _OverlayWidget(QWidget):
    def __init__(self, level_provider: Callable[[], float] | None = None) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(_WIDTH, _HEIGHT)
        self._pill = _PillWidget(self)
        self._pill.move(_PADDING, _PADDING)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 5)
        shadow.setColor(QColor(0, 0, 0, 110))
        self._pill.setGraphicsEffect(shadow)
        self._state = "idle"
        self._started_at = 0.0
        self._level_provider = level_provider
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)

    def _position(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        self.move(area.x() + (area.width() - _WIDTH) // 2,
                  area.y() + area.height() - _HEIGHT - _BOTTOM_MARGIN + _PADDING)

    @Slot(str)
    def set_state_slot(self, state: str) -> None:
        state = state if state in _LABELS else "idle"
        if state == self._state:
            return
        self._state = state
        self._pill.set_state(state)
        if state == "idle":
            self._timer.stop()
            self.hide()
            return
        self._started_at = time.monotonic()
        if state in ("recording", "processing"):
            self._timer.start()
        else:
            self._timer.stop()
        if not self.isVisible():
            self._position()
            self.show()

    def _tick(self) -> None:
        level = 0.0
        if self._state == "recording" and self._level_provider is not None:
            try:
                level = float(self._level_provider())
                if not math.isfinite(level):
                    level = 0.0
            except Exception:
                pass
        self._pill.set_frame(time.monotonic() - self._started_at, level)

    def closeEvent(self, event) -> None:
        self._timer.stop()
        super().closeEvent(event)


class Overlay:
    """Construct on the Qt main thread; set_state is safe from worker threads."""

    def __init__(self, level_provider: Callable[[], float] | None = None) -> None:
        self._widget = _OverlayWidget(level_provider)

    def set_state(self, state: str) -> None:
        if self._widget is None:
            return
        try:
            QMetaObject.invokeMethod(self._widget, "set_state_slot",
                                     Qt.QueuedConnection, Q_ARG(str, state))
        except RuntimeError:
            pass

    def stop(self) -> None:
        if self._widget is None:
            return
        try:
            QMetaObject.invokeMethod(self._widget, "close", Qt.QueuedConnection)
        except RuntimeError:
            pass
