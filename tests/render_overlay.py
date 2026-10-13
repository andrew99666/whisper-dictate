"""Render the production widget at several DPI scales, without microphone/API use."""
import os
import sys
import ctypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QFontDatabase
from PySide6.QtWidgets import QApplication

from overlay import _OverlayWidget, _font


def render_widget(state, scale):
    widget = _OverlayWidget()
    widget.set_state_slot(state)
    for level in (0.002, 0.009, 0.02, 0.035, 0.024, 0.013, 0.03, 0.019, 0.006):
        widget._pill.set_frame(12, level)
    widget._timer.stop()
    image = QImage(round(widget.width() * scale), round(widget.height() * scale),
                   QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(scale)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    widget.render(painter, QPoint(0, 0))
    painter.end()
    widget.close()
    return image


def main():
    native = "--native" in sys.argv
    app = QApplication(["overlay-preview"] + ([] if native else ["-platform", "offscreen"]))
    # Windows' offscreen backend doesn't discover installed system fonts.
    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    if not native:
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            assert QFontDatabase.addApplicationFont(str(fonts / name)) >= 0
    assert QFontDatabase.families(), "No fonts available for preview"
    if native:
        foreground = ctypes.windll.user32.GetForegroundWindow
        foreground.restype = ctypes.c_void_p
        before = foreground()
        widget = _OverlayWidget(lambda: 0.02)
        for state in ("recording", "processing", "muted"):
            widget.set_state_slot(state)
            app.processEvents()
            assert foreground() == before, "Overlay changed foreground focus"
        widget.set_state_slot("idle")
        widget.close()
        print("Native Windows focus check passed for all three visible states.")
    folder = Path(__file__).resolve().parents[1] / "ui_previews"
    folder.mkdir(exist_ok=True)
    states = ("recording", "processing", "muted")
    for scale in (1, 1.5, 2):
        for state in states:
            assert render_widget(state, scale).save(str(folder / f"overlay-{state}-{scale}x.png"))
    sheet = QImage(2160, 680, QImage.Format_ARGB32_Premultiplied)
    sheet.setDevicePixelRatio(2)
    sheet.fill(QColor("#eef0f3"))
    painter = QPainter(sheet)
    painter.fillRect(0, 170, 1080, 170, QColor("#101215"))
    for row in range(2):
        for column, state in enumerate(states):
            painter.setPen(QColor("#555d68") if row == 0 else QColor("#a9b0ba"))
            painter.setFont(_font(12))
            painter.drawText(24 + column * 360, 35 + row * 170, state.capitalize())
            painter.drawImage(QPoint(14 + column * 360, 50 + row * 170), render_widget(state, 2))
    painter.end()
    assert sheet.save(str(folder / "overlay-preview.png"))
    print(folder / "overlay-preview.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
