"""设置存取 + 开机自启（启动文件夹里的 .lnk）。"""
from __future__ import annotations

import json
import os
import subprocess
import sys

DEFAULTS = {
    "mouse_interval": 5.0,     # 鼠标轮询间隔（秒）
    "show_bluetooth": True,    # 是否显示蓝牙设备
    "start_hidden": False,     # 启动时只留托盘
    "disabled_devices": [],    # 设置里取消勾选的设备 key
}

_SHORTCUT_NAME = "设备电量.lnk"


def base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


SETTINGS_FILE = os.path.join(base_dir(), "settings.json")


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data.update(json.load(f) or {})
    except Exception:
        pass
    return data


def save(data: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 开机自启
def _startup_dir() -> str:
    return os.path.join(os.environ.get("APPDATA", ""),
                        r"Microsoft\Windows\Start Menu\Programs\Startup")


def shortcut_path() -> str:
    return os.path.join(_startup_dir(), _SHORTCUT_NAME)


def autostart_enabled() -> bool:
    return os.path.exists(shortcut_path())


def shortcut_target() -> str:
    """读 .lnk 指向的目标路径（读不到返回空串）。"""
    path = shortcut_path()
    if not os.path.exists(path):
        return ""
    ps = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
          "(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}').TargetPath").format(lnk=path)
    try:
        flags = 0x08000000 if os.name == "nt" else 0
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=20, creationflags=flags)
        return (r.stdout or "").strip()
    except Exception:
        return ""


def refresh_autostart() -> tuple[bool, str]:
    """自启开着、但快捷方式指向旧位置（程序被挪过目录）时自动修好。"""
    if not autostart_enabled():
        return False, "未开启"
    target, _ = _target_and_args()
    cur = shortcut_target()
    if cur and os.path.normcase(cur) == os.path.normcase(target) and os.path.exists(cur):
        return True, "ok"
    ok, msg = set_autostart(True)
    return ok, "已修正" if ok else msg


def _target_and_args() -> tuple[str, str]:
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    target = pyw if os.path.exists(pyw) else sys.executable
    return target, f'"{os.path.join(base_dir(), "main.py")}"'


def set_autostart(enabled: bool) -> tuple[bool, str]:
    """用 PowerShell 建/删快捷方式，失败返回 (False, 原因)。"""
    path = shortcut_path()
    try:
        if enabled:
            target, args = _target_and_args()
            ps = (
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{lnk}');"
                "$s.TargetPath='{t}';$s.Arguments='{a}';$s.WorkingDirectory='{wd}';"
                "$s.Description='设备电量';$s.Save()"
            ).format(lnk=path, t=target, a=args, wd=base_dir())
        else:
            if not os.path.exists(path):
                return True, ""
            os.remove(path)
            return True, ""
        flags = 0x08000000 if os.name == "nt" else 0
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                            "-Command", ps], capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           timeout=25, creationflags=flags)
        if r.returncode != 0 or not os.path.exists(path):
            return False, (r.stderr or "创建快捷方式失败").strip()[:120]
        return True, ""
    except Exception as e:
        return False, str(e)[:120]
