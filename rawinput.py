"""Map real mouse/keyboard input to the physical HID collection via Raw Input.

Windows delivers WM_INPUT with an hDevice handle for every input packet; that
handle resolves to a device interface path such as
``\\\\?\\hid#vid_248a&pid_5b2f&mi_00#...`` — i.e. it tells us which receiver the
mouse is really talking to.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

WM_INPUT = 0x00FF
RID_INPUT = 0x10000003
RIDI_DEVICENAME = 0x20000007
RIDEV_INPUTSINK = 0x00000100
HID_USAGE_PAGE_GENERIC = 0x01
HID_USAGE_GENERIC_MOUSE = 0x02
HID_USAGE_GENERIC_KEYBOARD = 0x06

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [("usUsagePage", wintypes.USHORT), ("usUsage", wintypes.USHORT),
                ("dwFlags", wintypes.DWORD), ("hwndTarget", wintypes.HWND)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [("dwType", wintypes.DWORD), ("dwSize", wintypes.DWORD),
                ("hDevice", wintypes.HANDLE), ("wParam", wintypes.WPARAM)]


user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterRawInputDevices.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT,
                                           wintypes.UINT]
user32.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                   ctypes.POINTER(wintypes.UINT), wintypes.UINT]
user32.GetRawInputData.restype = wintypes.UINT
user32.GetRawInputDeviceInfoW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPVOID,
                                          ctypes.POINTER(wintypes.UINT)]
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT


def device_name(handle) -> str:
    size = wintypes.UINT(0)
    user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, None, ctypes.byref(size))
    if not size.value:
        return ""
    buf = ctypes.create_unicode_buffer(size.value + 2)
    if user32.GetRawInputDeviceInfoW(handle, RIDI_DEVICENAME, buf, ctypes.byref(size)) < 0:
        return ""
    return buf.value


def watch(seconds: float, on_event):
    msg = wintypes.MSG()
    hits: dict[str, int] = {}

    def wndproc(hwnd, msg_id, wparam, lparam):
        if msg_id == WM_INPUT:
            size = wintypes.UINT(0)
            user32.GetRawInputData(lparam, RID_INPUT, None, ctypes.byref(size),
                                   ctypes.sizeof(RAWINPUTHEADER))
            buf = ctypes.create_string_buffer(max(size.value, 64))
            if user32.GetRawInputData(lparam, RID_INPUT, buf, ctypes.byref(size),
                                      ctypes.sizeof(RAWINPUTHEADER)) == size.value:
                hdr = ctypes.cast(buf, ctypes.POINTER(RAWINPUTHEADER)).contents
                name = device_name(hdr.hDevice)
                if name:
                    hits[name] = hits.get(name, 0) + 1
                    on_event(name, hits[name])
        return user32.DefWindowProcW(hwnd, msg_id, wparam, lparam)

    proc = WNDPROC(wndproc)
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(wc)
    wc.lpfnWndProc = proc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = "BatteryRawInputWatch"
    if not user32.RegisterClassExW(ctypes.byref(wc)):
        raise ctypes.WinError(ctypes.get_last_error())
    hwnd = user32.CreateWindowExW(0, wc.lpszClassName, "watch", 0, 0, 0, 0, 0,
                                  None, None, wc.hInstance, None)
    devs = (RAWINPUTDEVICE * 2)()
    devs[0].usUsagePage = HID_USAGE_PAGE_GENERIC
    devs[0].usUsage = HID_USAGE_GENERIC_MOUSE
    devs[0].dwFlags = RIDEV_INPUTSINK
    devs[0].hwndTarget = hwnd
    devs[1].usUsagePage = HID_USAGE_PAGE_GENERIC
    devs[1].usUsage = HID_USAGE_GENERIC_KEYBOARD
    devs[1].dwFlags = RIDEV_INPUTSINK
    devs[1].hwndTarget = hwnd
    if not user32.RegisterRawInputDevices(devs, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        raise ctypes.WinError(ctypes.get_last_error())

    end = time.time() + seconds
    while time.time() < end:
        while user32.PeekMessageW(ctypes.byref(msg), hwnd, 0, 0, 1):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.005)
    user32.DestroyWindow(hwnd)
    return hits


if __name__ == "__main__":
    import sys
    secs = float(sys.argv[1]) if len(sys.argv) > 1 else 15
    print(f"listening for raw input for {secs:g}s ...")

    def report(name, count):
        if count == 1:
            print(f"  {name}", flush=True)

    hits = watch(secs, report)
    print("\nsummary:")
    for k, v in hits.items():
        print(f"  {v:5d}  {k}")
