"""命令行入口。

    python main.py              打开面板
    python main.py --once       打印一次后退出（默认等 16 秒抓键盘心跳）
    python main.py --once --wait 30
    python main.py --json
    python main.py --list       列出所有 HID 接口（排障用）
"""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
from ctypes import wintypes

import hid_win as hw
import protocols as P

WINDOW_TITLE = "设备电量"


def _activate_existing() -> bool:
    """已经有实例在跑？把它叫到前台并返回 True（避免重复启动出现两套图标）。"""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]

    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    user32.SetForegroundWindow(hwnd)
    return True


class _NullIO:
    def write(self, *_a):
        pass

    def flush(self):
        pass

    def reconfigure(self, **_k):
        pass


def _utf8_console() -> None:
    """打包成无控制台的 exe 后 sys.stdout 是 None，这里兜个底。"""
    if sys.stdout is None:
        sys.stdout = _NullIO()
    if sys.stderr is None:
        sys.stderr = _NullIO()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def print_table(readings: list[P.Reading]) -> None:
    name_w = max([len(r.name) for r in readings] + [12])
    for r in readings:
        lvl = f"{r.level}%" if r.level is not None else "—"
        line = f"{r.name:<{name_w}}  {lvl:>4}  {r.status_text}"
        if r.detail:
            line += f"  · {r.detail}"
        print(line)


def _enable_dpi() -> None:
    """在高缩放（150%）下不糊：先声明 DPI 感知，再交给 Tk 按真实 DPI 缩放。"""
    try:
        # Per-Monitor V2
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    _enable_dpi()
    ap = argparse.ArgumentParser(description="2.4G / 蓝牙 设备电量")
    ap.add_argument("--once", action="store_true", help="打印一次后退出")
    ap.add_argument("--json", action="store_true", help="以 JSON 输出")
    ap.add_argument("--wait", type=float, default=16.0,
                    help="--once 时等待键盘推送电量的秒数（默认 16，键盘每 15 秒推一次）")
    ap.add_argument("--list", action="store_true", help="列出所有 HID 接口")
    ap.add_argument("--hidden", action="store_true", help="只留状态栏图标，不弹面板")
    args = ap.parse_args(argv)

    if args.list:
        for d in hw.enumerate_hid():
            print(d)
            print("   ", d.path)
        return 0

    if not (args.once or args.json) and _activate_existing():
        print("已经在运行了，已把面板叫到前台。")
        return 0

    if args.once or args.json:
        readings = P.collect(listen=args.wait)
        if args.json:
            print(json.dumps([
                {"name": r.name, "kind": r.kind, "level": r.level,
                 "status": r.status, "detail": r.detail,
                 "source": r.source, "transport": r.transport}
                for r in readings], ensure_ascii=False, indent=2))
        else:
            if any(r.status == "idle" and r.kind == "keyboard" for r in readings):
                print("（等待键盘推送电量：这段时间里按一下键盘任意键就能读到）")
            print_table(readings)
        return 0

    import viewer
    viewer.run(start_hidden=args.hidden)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
