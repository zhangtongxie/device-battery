"""Windows 通知区域图标：每台设备一个「圆环 + 设备图标」，纯 ctypes。

圆环按电量填充、颜色随电量变；中间是键盘/鼠标/耳机/手机的图标。
托盘必须有自己的窗口消息循环，所以跑在独立线程里；和 Tk 的交互一律通过队列。
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes

import hid_win as hw
import iconfx

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32", use_last_error=True)

WM_APP = 0x8000
WM_TRAY = WM_APP + 1
WM_TIMER = 0x0113
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111

NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_SHOWTIP = 0x01, 0x02, 0x04, 0x80
NOTIFYICON_VERSION_4 = 4

MF_STRING, MF_SEPARATOR, MF_GRAYED = 0x0000, 0x0800, 0x0001
TPM_RETURNCMD, TPM_RIGHTBUTTON = 0x0100, 0x0002

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH), ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uID", wintypes.UINT), ("uFlags", wintypes.UINT),
                ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD),
                ("dwStateMask", wintypes.DWORD), ("szInfo", wintypes.WCHAR * 256),
                ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", hw.GUID),
                ("hBalloonIcon", wintypes.HICON)]


user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                   wintypes.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.HWND,
                                   wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.TrackPopupMenu.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]


class Tray:
    """每台设备一个托盘图标；on_command("open"/"refresh"/"quit") 交给主线程。"""

    def __init__(self, snapshot, on_command, title: str = "设备电量"):
        self.snapshot = snapshot
        self.on_command = on_command
        self.title = title
        self.ok = False
        self._hwnd = 0
        self._uid = 0
        self._items: dict[str, dict] = {}
        self._light = iconfx.theme_is_light()
        self._warned = False
        self.last_error = ""
        self._extra = ""
        self._log_path = os.path.join(
            os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else
            os.path.dirname(os.path.abspath(__file__)), "tray.log")
        self._thread = threading.Thread(target=self._run, daemon=True)

    # ------------------------------------------------------------------
    def start(self) -> "Tray":
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._hwnd:
            user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)

    # ------------------------------------------------------------------
    def _tip(self, reading) -> str:
        level = "—" if reading.level is None else f"{reading.level}%"
        extra = "" if reading.status == "ok" else f"（{reading.status_text}）"
        return f"{reading.name} {level}{extra}"[:120]

    def _diag(self) -> str:
        """失败时抓一点现场：任务栏窗口、能不能给它发消息、是否管理员。"""
        try:
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                                                   wintypes.LPARAM, wintypes.UINT, wintypes.UINT,
                                                   ctypes.POINTER(ctypes.c_size_t)]
            tray = user32.FindWindowW("Shell_TrayWnd", None)
            if not tray:
                self._extra = "找不到任务栏窗口（explorer 没运行？）"
                return "（" + self._extra + "）"
            res = ctypes.c_size_t()
            ok = user32.SendMessageTimeoutW(tray, 0x0401, 0, 0, 0x0002, 300, ctypes.byref(res))
            elevated = bool(shell32.IsUserAnAdmin())
            self._extra = f"任务栏可通信={bool(ok)} 管理员={elevated}"
            return "（" + self._extra + "）"
        except Exception as e:
            return f"（诊断异常 {e}）"

    def _log(self, text: str) -> None:
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {text}\n")
        except Exception:
            pass

    def _add(self, key: str, reading) -> None:
        self._uid += 1
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd = self._hwnd
        nid.uID = self._uid
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP | NIF_SHOWTIP
        nid.uCallbackMessage = WM_TRAY
        nid.hIcon = iconfx.icon_for(reading.level, reading.kind, self._light)
        nid.szTip = self._tip(reading)
        if not shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)):
            err = ctypes.get_last_error()
            self.last_error = f"Shell_NotifyIcon 失败，错误码 {err}" + self._diag()
            if not self._warned:
                self._warned = True
                self._log(f"NIM_ADD 失败 err={err}（hwnd={self._hwnd} hIcon={nid.hIcon}）")
                print("[tray] 图标添加失败（错误码", err, "）", flush=True)
            return
        self.ok = True
        self.last_error = ""
        self._extra = ""
        nid.uVersion = NOTIFYICON_VERSION_4
        shell32.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(nid))
        self._items[key] = {"nid": nid, "level": reading.level,
                            "kind": reading.kind, "tip": nid.szTip,
                            "status": reading.status}
        self._log(f"图标已添加 key={key} uid={nid.uID} level={reading.level}")

    def _update(self, key: str, reading) -> None:
        item = self._items[key]
        tip = self._tip(reading)
        need_icon = (reading.level != item["level"] or reading.kind != item["kind"]
                     or reading.status != item["status"])
        if not need_icon and tip == item["tip"]:
            return
        nid = item["nid"]
        if need_icon:
            nid.hIcon = iconfx.icon_for(reading.level, reading.kind, self._light)
        nid.szTip = tip
        shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
        item.update(level=reading.level, kind=reading.kind, tip=tip, status=reading.status)

    def _remove(self, key: str) -> None:
        item = self._items.pop(key, None)
        if item:
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(item["nid"]))

    # ------------------------------------------------------------------
    def _run(self) -> None:
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(wc)
        self._proc = WNDPROC(self._wndproc)
        wc.lpfnWndProc = ctypes.cast(self._proc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = "BatteryTrayWnd"
        user32.RegisterClassExW(ctypes.byref(wc))
        self._hwnd = user32.CreateWindowExW(0, wc.lpszClassName, self.title, 0,
                                            0, 0, 0, 0, None, None, hinst, None)
        user32.SetTimer(self._hwnd, 1, 1000, None)
        try:
            elevated = bool(shell32.IsUserAnAdmin())
        except Exception:
            elevated = False
        self._log(f"托盘线程启动 hwnd={self._hwnd} elevated={elevated} pid={os.getpid()}")
        self._tick()                       # 立刻加图标，不等第一个 timer

        msg = wintypes.MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r in (0, -1):
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        for key in list(self._items):
            self._remove(key)

    # ------------------------------------------------------------------
    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAY:
            low = lparam & 0xFFFF
            # NOTIFYICON_VERSION_4 用 NIN_SELECT / WM_CONTEXTMENU，老版本用 WM_LBUTTONUP 等
            if low in (0x0400, 0x0401, 0x0202):
                self.on_command("open")
            elif low in (0x007B, 0x0205, 0x0204):
                self._menu()
            return 0
        if msg == WM_TIMER:
            self._tick()
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == 1:
                self.on_command("open")
            elif cmd == 2:
                self.on_command("quit")
            elif cmd == 3:
                self.on_command("refresh")
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self) -> None:
        hmenu = user32.CreatePopupMenu()
        for item in self._items.values():
            user32.AppendMenuW(hmenu, MF_STRING | MF_GRAYED, 0, item["tip"])
        if self._items:
            user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, 1, "打开面板")
        user32.AppendMenuW(hmenu, MF_STRING, 3, "立即刷新")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, 2, "退出")
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self._hwnd)
        cmd = user32.TrackPopupMenu(hmenu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                    pt.x, pt.y, 0, self._hwnd, None)
        if cmd:
            user32.PostMessageW(self._hwnd, WM_COMMAND, cmd, 0)
        user32.DestroyMenu(hmenu)

    # ------------------------------------------------------------------
    def _tick(self) -> None:
        try:
            snap = self.snapshot()
            light = iconfx.theme_is_light()
            if light != self._light:
                self._light = light
                for item in self._items.values():
                    item["level"] = object()      # 强制重画
            readings = list(getattr(snap, "readings", []))
            wanted = {r.key: r for r in readings}
            for key in list(self._items):
                if key not in wanted:
                    self._remove(key)
            for key, reading in wanted.items():
                if key in self._items:
                    self._update(key, reading)
                else:
                    self._add(key, reading)
        except Exception as e:
            self.last_error = f"{type(e).__name__}: {e}"
            if not self._warned:
                self._warned = True
                import traceback
                self._log("tick 异常:\n" + traceback.format_exc())
