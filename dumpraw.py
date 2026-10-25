"""原始报文抓取：给「加新设备 / 找充电标志位」用。

用法：
    python main.py --dump            # 默认 30 秒
    python main.py --dump --seconds 60

输出写到 exe 同目录的 `battery-dump.txt`，同时打印到控制台。
中途插上/拔掉充电线，就能看到哪一位跟着变。
"""
from __future__ import annotations

import os
import sys
import threading
import time

import bt_battery
import hid_win as hw
import protocols as P


def _base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _hex(data: bytes) -> str:
    return " ".join(f"{b:02X}" for b in data)


def run(seconds: float = 30.0) -> str:
    path = os.path.join(_base_dir(), "battery-dump.txt")
    lines: list[str] = []
    lock = threading.Lock()
    stop = threading.Event()

    def add(text: str) -> None:
        with lock:
            lines.append(text)
            try:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(text + "\n")
            except Exception:
                pass
        print(text, flush=True)

    # 记录开始时间：每次运行都另起一段
    try:
        open(path, "w", encoding="utf-8").close()
    except Exception:
        pass
    add(f"# dump {time.strftime('%Y-%m-%d %H:%M:%S')}  {seconds:.0f}s")

    def kbd_loop() -> None:
        dev = P.find_xs98t()
        if not dev:
            add("# 没有找到键盘接收器 05AC:024F")
            return
        add(f"# 键盘接收器 path={dev.path} in_len={dev.in_len}")
        h = hw.open_device(dev.path, hw.GENERIC_READ, overlapped=True)
        if not h:
            add("# 打不开键盘接收器")
            return
        try:
            while not stop.is_set():
                data = hw.read_report(h, dev.in_len, timeout_ms=400)
                if data:
                    add(f"K {time.strftime('%H:%M:%S')} {_hex(data)}")
        finally:
            hw.close_handle(h)

    t = threading.Thread(target=kbd_loop, daemon=True)
    t.start()

    # 每 2 秒抓一次鼠标邮箱
    t0 = time.time()
    while time.time() - t0 < seconds:
        dev = P.find_sc580_mailbox()
        if not dev:
            add(f"M {time.strftime('%H:%M:%S')} 没有找到 248A:5B2F")
        else:
            h = hw.open_device(dev.path, hw.GENERIC_READ | hw.GENERIC_WRITE)
            if h:
                try:
                    data = P._sc580_fetch(h, dev.feat_len)
                    if data:
                        add(f"M {time.strftime('%H:%M:%S')} {_hex(data)}")
                    else:
                        add(f"M {time.strftime('%H:%M:%S')} <无响应>")
                finally:
                    hw.close_handle(h)
        time.sleep(2.0)

    stop.set()

    # 蓝牙快照（只列真的带电池的设备）
    try:
        for r in P.read_bluetooth():
            add(f"B {r.name} level={r.level} status={r.status} id={r.key}")
    except Exception as e:
        add(f"# 蓝牙枚举失败：{e}")

    add("# dump end")
    return path
