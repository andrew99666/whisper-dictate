"""System tray icon: idle / recording / processing states, input device picker, quit."""
from __future__ import annotations

from typing import Callable
import pystray
import sounddevice as sd
from PIL import Image, ImageDraw


def _make_icon(color: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 56, 56], fill=color, outline="black")
    return img


_ICONS = {
    "idle": _make_icon("#808080"),
    "recording": _make_icon("#E53935"),
    "processing": _make_icon("#FB8C00"),
}

_TITLES = {
    "idle": "Whisper Dictate (idle)",
    "recording": "Whisper Dictate (recording)",
    "processing": "Whisper Dictate (processing)",
}

_API_SHORT = {
    "Windows WASAPI": "WASAPI",
    "Windows DirectSound": "DSound",
    "Windows WDM-KS": "WDM-KS",
    "MME": "MME",
}


def _wasapi_index() -> int | None:
    try:
        for i, a in enumerate(sd.query_hostapis()):
            if a.get("name") == "Windows WASAPI":
                return i
    except Exception:
        pass
    return None


def list_input_devices(show_all_backends: bool = False) -> list[tuple[int, str]]:
    """Return (index, display_name) for input-capable devices.

    By default shows only WASAPI endpoints (one entry per physical device,
    matching what apps like Google Meet display). Set show_all_backends=True
    to see every backend (MME, DirectSound, WASAPI, WDM-KS) — useful when a
    device only works through a specific backend (e.g. some Bluetooth HFP mics).
    """
    out: list[tuple[int, str]] = []
    try:
        devices = sd.query_devices()
    except Exception:
        return out
    wasapi = _wasapi_index()
    # Fall back to all backends if WASAPI somehow isn't available
    filter_wasapi = (not show_all_backends) and wasapi is not None
    for i, d in enumerate(devices):
        if d.get("max_input_channels", 0) < 1:
            continue
        if filter_wasapi and d.get("hostapi") != wasapi:
            continue
        try:
            api_name = sd.query_hostapis(d["hostapi"])["name"]
        except Exception:
            api_name = "?"
        name = (d.get("name") or "?")[:50]
        if show_all_backends:
            out.append((i, f"{name} [{_API_SHORT.get(api_name, api_name)}]"))
        else:
            out.append((i, name))
    return out


class Tray:
    def __init__(
        self,
        on_quit: Callable[[], None],
        current_device: int | None,
        on_select_device: Callable[[int | None], None],
        show_all_backends: bool = False,
    ):
        self._on_quit = on_quit
        self._current_device = current_device
        self._on_select_device = on_select_device

        device_items: list[pystray.MenuItem] = [
            pystray.MenuItem(
                "System default",
                self._make_select(None),
                checked=lambda item: self._current_device is None,
                radio=True,
            )
        ]
        for idx, label in list_input_devices(show_all_backends=show_all_backends):
            device_items.append(
                pystray.MenuItem(
                    label,
                    self._make_select(idx),
                    checked=lambda item, i=idx: self._current_device == i,
                    radio=True,
                )
            )

        self.icon = pystray.Icon(
            "whisper-dictate",
            _ICONS["idle"],
            _TITLES["idle"],
            menu=pystray.Menu(
                pystray.MenuItem("Input device", pystray.Menu(*device_items)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", self._quit),
            ),
        )

    def _make_select(self, idx: int | None):
        def handler(icon, item):
            self._current_device = idx
            try:
                self._on_select_device(idx)
            finally:
                self.icon.update_menu()
        return handler

    def _quit(self, _icon, _item):
        try:
            self._on_quit()
        finally:
            self.icon.stop()

    def set_state(self, state: str) -> None:
        if state not in _ICONS:
            return
        self.icon.icon = _ICONS[state]
        self.icon.title = _TITLES[state]

    def run(self) -> None:
        self.icon.run()

    def stop(self) -> None:
        self.icon.stop()
