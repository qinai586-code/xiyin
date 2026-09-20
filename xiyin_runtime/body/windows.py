"""Optional, explicitly window-scoped Win32 transport. No calls occur on import.

References: Microsoft Learn winuser SendInput, GetClientRect,
GetDpiForWindow and SetThreadDpiAwarenessContext. SendInput reports dispatch,
not a completed UI action, and cannot bypass UIPI/integrity restrictions.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os

from .actions import DesktopAdapter
from .models import InputRejected


KEYS = {**{chr(value): value for value in range(ord("A"), ord("Z") + 1)},
        **{str(value): ord(str(value)) for value in range(10)},
        "LEFT": 0x25, "UP": 0x26, "RIGHT": 0x27, "DOWN": 0x28,
        "SPACE": 0x20, "ENTER": 0x0D, "ESC": 0x1B, "TAB": 0x09, "SHIFT": 0x10}


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_int32), ("dy", ctypes.c_int32), ("mouseData", ctypes.c_uint32),
                ("dwFlags", ctypes.c_uint32), ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _KeyboardInput(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_uint16), ("wScan", ctypes.c_uint16), ("dwFlags", ctypes.c_uint32),
                ("time", ctypes.c_uint32), ("dwExtraInfo", ctypes.c_size_t)]


class _HardwareInput(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_uint32), ("wParamL", ctypes.c_uint16), ("wParamH", ctypes.c_uint16)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput), ("ki", _KeyboardInput), ("hi", _HardwareInput)]


class _Input(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", ctypes.c_uint32), ("value", _InputUnion)]


class CtypesWin32API:
    """Small Win32 API boundary, injectable for tests without device access."""
    def __init__(self):
        if os.name != "nt":
            raise RuntimeError("Win32 desktop transport requires Windows")
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        u = self.user32
        u.IsWindow.argtypes, u.IsWindow.restype = [wintypes.HWND], wintypes.BOOL
        u.GetForegroundWindow.argtypes, u.GetForegroundWindow.restype = [], wintypes.HWND
        u.GetClientRect.argtypes, u.GetClientRect.restype = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL
        u.ClientToScreen.argtypes, u.ClientToScreen.restype = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL
        u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [wintypes.HWND], wintypes.UINT
        u.GetWindowTextLengthW.argtypes, u.GetWindowTextLengthW.restype = [wintypes.HWND], ctypes.c_int
        u.GetWindowTextW.argtypes, u.GetWindowTextW.restype = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetSystemMetrics.argtypes, u.GetSystemMetrics.restype = [ctypes.c_int], ctypes.c_int
        u.GetAsyncKeyState.argtypes, u.GetAsyncKeyState.restype = [ctypes.c_int], ctypes.c_short
        u.SendInput.argtypes, u.SendInput.restype = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int], wintypes.UINT
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p

    @contextmanager
    def _physical_coordinates(self):
        previous = self.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
        if not previous:
            raise OSError("Cannot establish thread-local physical-pixel coordinates")
        try:
            yield
        finally:
            if not self.user32.SetThreadDpiAwarenessContext(previous):
                raise OSError("Failed to restore thread DPI context")

    def is_window(self, hwnd):
        return bool(self.user32.IsWindow(hwnd))

    def foreground(self):
        return int(self.user32.GetForegroundWindow() or 0)

    def key_pressed(self, virtual_key):
        return bool(self.user32.GetAsyncKeyState(virtual_key) & 0x8000)

    def window_details(self, hwnd):
        if not self.is_window(hwnd):
            raise ValueError("Authorized HWND no longer exists")
        with self._physical_coordinates():
            rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
            if not self.user32.GetClientRect(hwnd, ctypes.byref(rect)) or not self.user32.ClientToScreen(hwnd, ctypes.byref(point)):
                raise OSError("Cannot read the authorized client rectangle")
            dpi = self.user32.GetDpiForWindow(hwnd)
            if dpi == 0:
                raise OSError("Cannot read the authorized window DPI")
            length = min(self.user32.GetWindowTextLengthW(hwnd), 8192)
            title = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, title, length + 1)
            pid = wintypes.DWORD()
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            return {"width": rect.right - rect.left, "height": rect.bottom - rect.top,
                    "x": point.x, "y": point.y, "dpi": dpi, "title": title.value, "process_id": pid.value}

    def _send(self, values):
        records = (_Input * len(values))(*values)
        sent = self.user32.SendInput(len(records), records, ctypes.sizeof(_Input))
        if sent != len(records):
            raise OSError(f"SendInput dispatched {sent}/{len(records)} events; completion unknown (UIPI may block input)")

    def key(self, virtual_key, *, up=False):
        flags = (2 if up else 0) | (1 if virtual_key in {0x25, 0x26, 0x27, 0x28} else 0)
        event = _Input(type=1)
        event.ki = _KeyboardInput(wVk=virtual_key, dwFlags=flags)
        self._send([event])

    def click(self, hwnd, x, y):
        with self._physical_coordinates():
            details = self.window_details(hwnd)
            if self.foreground() != hwnd or not 0 <= x < details["width"] or not 0 <= y < details["height"]:
                raise InputRejected("Click target is outside the focused authorized client area")
            if self.key_pressed(1):
                raise InputRejected("Mouse button is already held; not taking ownership of existing input")
            left, top = self.user32.GetSystemMetrics(76), self.user32.GetSystemMetrics(77)
            width, height = self.user32.GetSystemMetrics(78), self.user32.GetSystemMetrics(79)
            if width <= 1 or height <= 1:
                raise OSError("Invalid virtual desktop geometry")
            if not left <= details["x"] + x < left + width or not top <= details["y"] + y < top + height:
                raise InputRejected("Client target is outside the visible virtual desktop")
            absolute_x = round((details["x"] + x - left) * 65535 / (width - 1))
            absolute_y = round((details["y"] + y - top) * 65535 / (height - 1))
            move, down, up = _Input(type=0), _Input(type=0), _Input(type=0)
            move.mi = _MouseInput(dx=absolute_x, dy=absolute_y, dwFlags=0x0001 | 0x8000 | 0x4000)
            down.mi = _MouseInput(dwFlags=0x0002)
            up.mi = _MouseInput(dwFlags=0x0004)
            try:
                self._send([move, down, up])
            except Exception:
                self._send([up])  # A partial batch may have pressed the button.
                raise

    def capture_png(self, hwnd):
        from PIL import ImageGrab  # Optional; never installed by this module.
        with self._physical_coordinates():
            details = self.window_details(hwnd)
            if self.foreground() != hwnd:
                raise InputRejected("Screenshots require the authorized window to be foreground")
            image = ImageGrab.grab(bbox=(details["x"], details["y"], details["x"] + details["width"],
                                        details["y"] + details["height"]), all_screens=True)
            output = io.BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()


class Win32DesktopDriver:
    def __init__(self, hwnd: int, *, capture=False, api=None):
        if type(hwnd) is not int or hwnd <= 0:
            raise ValueError("A positive, explicitly authorized HWND is required")
        self.hwnd, self.capture = hwnd, capture
        self._api = api
        self._pressed = set()
        self._unavailable_reason = "Win32 desktop transport requires Windows"
        if api is None and os.name == "nt":
            try:
                self._api = CtypesWin32API()
            except Exception as exc:
                self._unavailable_reason = str(exc)
        self.available = self._api is not None

    @property
    def window_id(self):
        return f"hwnd:{self.hwnd}"

    async def health(self):
        if self._api is None:
            return {"available": False, "detail": self._unavailable_reason}
        return {"available": self._api.is_window(self.hwnd), "detail": "Explicit HWND Win32 transport; screenshot is optional"}

    def _require_foreground(self):
        if self._api is None or not self._api.is_window(self.hwnd) or self._api.foreground() != self.hwnd:
            # Raised before any SendInput call, so the receipt can say plainly
            # that nothing was dispatched rather than leaving it unknown.
            raise InputRejected("Authorized HWND must exist and be foreground; no focus stealing")

    async def current_window(self):
        if self._api is None:
            raise RuntimeError(self._unavailable_reason)
        return f"hwnd:{self._api.foreground()}"

    async def observe(self):
        if self._api is None:
            raise RuntimeError(self._unavailable_reason)
        details = self._api.window_details(self.hwnd)
        payload = {"title": details["title"], "process_id": details["process_id"],
                   "coordinate_space": "client_physical_pixels", "window_dpi": details["dpi"],
                   "screenshot": {"available": False}}
        if self.capture:
            try:
                self._require_foreground()
                image = self._api.capture_png(self.hwnd)
                if len(image) > 8 * 1024 * 1024:
                    raise ValueError("Screenshot exceeds the adapter size limit")
                payload["screenshot"] = {"available": True, "encoding": "png/base64",
                                         "data": base64.b64encode(image).decode("ascii"),
                                         "sha256": hashlib.sha256(image).hexdigest()}
            except Exception as exc:
                payload["screenshot"] = {"available": False, "detail": f"{type(exc).__name__}: {exc}"}
        revision = hashlib.sha256(json.dumps(details, sort_keys=True).encode()).hexdigest()
        return {"window_id": await self.current_window(), "width": details["width"], "height": details["height"],
                "dpi": (details["dpi"] / 96, details["dpi"] / 96), "revision": revision, "payload": payload}

    async def send(self, operation, arguments):
        self._require_foreground()
        if operation == "click":
            x, y = arguments.get("x"), arguments.get("y")
            if type(x) is not int or type(y) is not int:
                raise InputRejected("Click coordinates must be integer client pixels")
            details = self._api.window_details(self.hwnd)
            if not 0 <= x < details["width"] or not 0 <= y < details["height"]:
                raise InputRejected("Click is outside the client rectangle")
            self._api.click(self.hwnd, x, y)
        elif operation == "key_down":
            key = arguments.get("key")
            if key not in KEYS:
                raise InputRejected("Key is outside the restricted key set (no Win/Alt/Ctrl system chords)")
            if self._api.key_pressed(KEYS[key]):
                raise InputRejected("Key is already physically pressed; existing input is not owned by this adapter")
            self._pressed.add(key)
            self._api.key(KEYS[key])
        else:
            raise InputRejected("Unsupported Win32 operation")

    async def release_key(self, key):
        if key in self._pressed:
            self._api.key(KEYS[key], up=True)
            self._pressed.discard(key)

    async def verify(self, request):
        condition = request.arguments.get("postcondition")
        if not isinstance(condition, dict):
            return None
        if self._api is None:
            return None
        if condition.get("kind") == "foreground_window":
            return self._api.foreground() == self.hwnd
        if condition.get("kind") in {"window_title_equals", "window_title_contains"}:
            value = condition.get("value")
            if not isinstance(value, str) or not value:
                return None
            title = self._api.window_details(self.hwnd)["title"]
            return title == value if condition["kind"] == "window_title_equals" else value in title
        return None


def win32_desktop_adapter(hwnd: int, *, capture=False, api=None) -> DesktopAdapter:
    driver = Win32DesktopDriver(hwnd, capture=capture, api=api)
    return DesktopAdapter(driver=driver, allowed_window=driver.window_id, version="win32-1")
