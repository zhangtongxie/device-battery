"""排障/逆向工具：看接口、看报文、看电量特征。

    python probe.py list                     列出所有 HID 接口
    python probe.py caps 05ac:024f           打印接口的 report id / usage
    python probe.py watch 05ac:024f 20       监听并十六进制打印输入报文
    python probe.py feature 248a:5b2f        逐个 Report ID 读 Feature Report
    python probe.py bt                       列出蓝牙设备及其电量
    python probe.py raw 15                   监听并打印 Raw Input 设备路径
"""
from __future__ import annotations

import argparse
import ctypes
import sys
import time
from ctypes import wintypes

import hid_win as hw


def _match(d, spec: str) -> bool:
    return spec.lower() in f"{d.vid}:{d.pid}".lower() or spec.lower() in d.label.lower()


def cmd_list(_args) -> int:
    for d in hw.enumerate_hid():
        print(d)
        print("   ", d.path)
    return 0


def cmd_caps(args) -> int:
    import caps as capsmod
    for d in hw.enumerate_hid():
        if _match(d, args.spec):
            capsmod.dump(d)
    return 0


def cmd_watch(args) -> int:
    devs = [d for d in hw.enumerate_hid() if _match(d, args.spec) and d.in_len]
    handles = []
    for d in devs:
        h = hw.open_device(d.path, hw.GENERIC_READ, overlapped=True)
        print(f"{'打开成功' if h else '打开失败'}  {d}")
        if h:
            handles.append((d, h))
    if not handles:
        return 1
    end = time.perf_counter() + args.seconds
    while time.perf_counter() < end:
        for d, h in handles:
            data = hw.read_report(h, d.in_len, timeout_ms=50)
            if data is not None:
                print(f"{time.strftime('%H:%M:%S')} {d.id} mi={d.mi} "
                      f"up={d.usage_page:04X} [{len(data):3d}] {data.hex(' ')}")
        time.sleep(0.01)
    for _, h in handles:
        hw.close_handle(h)
    return 0


def cmd_feature(args) -> int:
    for d in hw.enumerate_hid():
        if not _match(d, args.spec) or not d.feat_len:
            continue
        h = hw.open_device(d.path, hw.GENERIC_READ | hw.GENERIC_WRITE)
        if not h:
            h = hw.open_device(d.path, hw.GENERIC_READ)
        print(f"\n### {d}  特征报文长度={d.feat_len}")
        if not h:
            print("   打不开")
            continue
        for rid in range(256):
            r = hw.get_feature(h, rid, d.feat_len)
            if r is None:
                continue
            if any(r[1:]):
                print(f"   rid {rid:02X}: {r.hex(' ')}")
        hw.close_handle(h)
    return 0


def cmd_bt(_args) -> int:
    import bt_battery
    for d in bt_battery.list_bt_devices():
        print(d)
        print("   ", d.instance_id)
    return 0


def cmd_raw(args) -> int:
    import rawinput
    print(f"监听 {args.seconds:g} 秒 Raw Input ……（注意：某些远程/沙箱会话收不到）")

    def show(name, n):
        if n == 1:
            print("  ", name, flush=True)

    hits = rawinput.watch(args.seconds, show)
    for k, v in hits.items():
        print(f"{v:5d}  {k}")
    return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="设备电量 - 排障工具")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list").set_defaults(fn=cmd_list)

    p = sub.add_parser("caps")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_caps)

    p = sub.add_parser("watch")
    p.add_argument("spec")
    p.add_argument("seconds", nargs="?", type=float, default=15)
    p.set_defaults(fn=cmd_watch)

    p = sub.add_parser("feature")
    p.add_argument("spec")
    p.set_defaults(fn=cmd_feature)

    sub.add_parser("bt").set_defaults(fn=cmd_bt)

    p = sub.add_parser("raw")
    p.add_argument("seconds", nargs="?", type=float, default=15)
    p.set_defaults(fn=cmd_raw)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
