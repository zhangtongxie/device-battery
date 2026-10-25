"""协议层：每台设备一个 profile，负责把 HID 报文翻译成电量。

已实现并实测：
  * GANSS XS98T 键盘（2.4G 接收器 05AC:024F）
  * 狼蛛 SC580 鼠标（2.4G 接收器 248A:5B2F 的 Feature「邮箱」）
  * 蓝牙设备（耳机 / 手机 / 手柄 …… 走 Windows 的 DEVPKEY_Bluetooth_Battery）
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import hid_win as hw
import bt_battery


# ---------------------------------------------------------------------------
# 通用结果
# ---------------------------------------------------------------------------
STATUS_TEXT = {
    "ok": "正常",
    "idle": "休眠中",
    "cached": "缓存值",
    "offline": "未连接",
    "unsupported": "暂不支持",
    "error": "读取失败",
}


# -- 本地缓存 -------------------------------------------------------------
# 两块 2.4G 设备都是「有事件才上报」：键盘要按键，鼠标要重新连接。
# 所以把最后一次读数存成一个小 JSON，重启面板时先显示它。
import json
import os
import sys

if getattr(sys, "frozen", False):          # PyInstaller 单文件：缓存放 exe 旁边
    _BASE_DIR = os.path.dirname(sys.executable)
else:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(_BASE_DIR, "battery-cache.json")


def _load_cache() -> dict:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or {}
    except Exception:
        return {}


def _save_cache(data: dict) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass


def remember(key: str, level: int) -> None:
    data = _load_cache()
    data[key] = {"level": int(level), "ts": time.time()}
    _save_cache(data)


def cached(key: str) -> tuple[int | None, float]:
    item = _load_cache().get(key) or {}
    level = item.get("level")
    if isinstance(level, int) and 0 <= level <= 100:
        return level, float(item.get("ts") or 0.0)
    return None, 0.0


@dataclass
class Reading:
    key: str
    name: str
    kind: str = "other"          # keyboard / mouse / headset / phone / other
    level: int | None = None
    charging: bool | None = None
    status: str = "ok"
    detail: str = ""
    source: str = ""
    transport: str = "2.4G"
    updated: float = 0.0
    raw: list[str] = field(default_factory=list)

    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, self.status)

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.updated) if self.updated else 0.0

    def age_text(self) -> str:
        if not self.updated:
            return ""
        s = int(self.age)
        if s < 90:
            return "刚刚"
        if s < 3600:
            return f"{s // 60} 分钟前"
        return f"{s // 3600} 小时前"


# ---------------------------------------------------------------------------
# GANSS XS98T —— usage page 0xFF60 / usage 0x61, 33 字节报文
#
# 实测帧（键盘唤醒时会定期推送）：
#     00 20 01 00 39 00 … 00 5A      <- 0x20 = 电量帧, 第 5 字节 0x39 = 57%
#     00 0C 10 00 …       1C         <- 0x0C = 链路/握手帧
# 校验：最后一字节 = 中间所有字节之和的低 8 位。
# ---------------------------------------------------------------------------
XS98T_VID = 0x05AC
XS98T_PID = 0x024F
FRAME_BATTERY = 0x20
FRAME_LINK = 0x0C


def _checksum_ok(frame: bytes) -> bool:
    if len(frame) < 4:
        return False
    return (sum(frame[1:-1]) & 0xFF) == frame[-1]


def find_xs98t() -> hw.HidDevice | None:
    for d in hw.enumerate_hid():
        if (d.vid == "05ac" and d.pid == "024f"
                and d.usage_page == 0xFF60 and d.in_len == 33):
            return d
    return None


def _poke(dev: hw.HidDevice) -> None:
    """往 64 字节通道写一帧空报文，试图把键盘从省电模式叫醒（失败也无所谓）。"""
    for d in hw.enumerate_hid():
        if d.vid == "05ac" and d.pid == "024f" and d.in_len == 65:
            h = hw.open_device(d.path, hw.GENERIC_READ | hw.GENERIC_WRITE)
            if h:
                try:
                    hw.write_report(h, bytes(d.out_len))
                finally:
                    hw.close_handle(h)
            return


def read_xs98t(listen: float = 4.0, wake: bool = True) -> Reading:
    dev = find_xs98t()
    if not dev:
        return Reading("xs98t", "GANSS XS98T", "keyboard", status="offline",
                       detail="没有找到 05AC:024F 的 2.4G 接收器", source="xs98t")

    if wake:
        _poke(dev)

    h = hw.open_device(dev.path, hw.GENERIC_READ, overlapped=True)
    if not h:
        return Reading("xs98t", "GANSS XS98T", "keyboard", status="error",
                       detail="打不开接收器的电量通道", source="xs98t")

    frames: list[str] = []
    deadline = time.perf_counter() + listen
    try:
        while time.perf_counter() < deadline:
            data = hw.read_report(h, dev.in_len, timeout_ms=200)
            if data is None:
                continue
            frames.append(data.hex(" "))
            if not _checksum_ok(data):
                continue
            cmd = data[1]
            if cmd == FRAME_BATTERY and len(data) >= 6:
                level = data[4]
                if 0 <= level <= 100:
                    remember("xs98t", level)
                    return Reading("xs98t", "GANSS XS98T", "keyboard", level=level,
                                   status="ok", source="xs98t",
                                   detail="0x20 状态帧", updated=time.time(), raw=frames)
    finally:
        hw.close_handle(h)

    level, ts = cached("xs98t")
    if level is not None:
        return Reading("xs98t", "GANSS XS98T", "keyboard", level=level, status="cached",
                       updated=ts, source="xs98t", raw=frames,
                       detail="键盘在省电，显示上次读数；按任意键可更新")
    return Reading("xs98t", "GANSS XS98T", "keyboard", status="idle",
                   detail="没收到电量帧：键盘在省电。按任意键后再刷新。",
                   source="xs98t", raw=frames)


# ---------------------------------------------------------------------------
# 狼蛛 SC580 —— 接收器 248A:5B2F，目前只做识别，不做读数
# ---------------------------------------------------------------------------
SC580_VID = 0x248A
SC580_PID = 0x5B2F


def find_sc580() -> hw.HidDevice | None:
    for d in hw.enumerate_hid():
        if d.vid == "248a" and d.pid == "5b2f" and d.usage_page == 0xFFEF:
            return d
    return None


# 接收器上还有一路 32 字节 Feature Report（mi_01 col04, Report ID 0x0C），是个「邮箱」。
# 查询要两步（少一步就只能捡到上次的缓存）：
#     1) 写 0C 01 20 00 0F 01 10 00   —— 让接收器去问鼠标要状态
#     2) 写 0C 01 20 00 10 01 10 00   —— 把结果取出来
#     3) 读回 0x0C
# 读回的内容：
#     0C 01 20 00 | 10 01 10 00 | "M137" | 28 01 | 00 25 | 46 FF | 25 00 | ...
#                                型号              3.7V           37%
# 下标 18 = 电量百分比；下标 15 = 电压（0x25 = 3.7V）；8–11 型号；24–27 固件。
_SC580_CACHE: dict = {"level": None, "ts": 0.0, "model": "", "fw": ""}
_SC580_REQ = bytes([0x0C, 0x01, 0x20, 0x00, 0x0F, 0x01, 0x10, 0x00])
_SC580_GET = bytes([0x0C, 0x01, 0x20, 0x00, 0x10, 0x01, 0x10, 0x00])


def find_sc580_mailbox() -> hw.HidDevice | None:
    for d in hw.enumerate_hid():
        if d.vid == "248a" and d.pid == "5b2f" and d.feat_len == 33:
            return d
    return None


def _sc580_fetch(h, size: int) -> bytes | None:
    """走一次「0x0F 请求 → 0x10 取回」，成功返回整帧。"""
    pkt = bytearray(size)
    pkt[:len(_SC580_REQ)] = _SC580_REQ
    hw.set_feature(h, bytes(pkt))
    time.sleep(0.12)
    pkt[:len(_SC580_GET)] = _SC580_GET
    hw.set_feature(h, bytes(pkt))
    time.sleep(0.25)
    data = hw.get_feature(h, 0x0C, size)
    if data and len(data) > 18 and any(data[8:]):
        return data
    return None


def read_sc580(retries: int = 2) -> Reading:
    dev = find_sc580_mailbox()
    if not dev:
        return Reading("sc580", "狼蛛 SC580", "mouse", status="offline",
                       detail="没有找到 248A:5B2F 的接收器", source="sc580")

    h = hw.open_device(dev.path, hw.GENERIC_READ | hw.GENERIC_WRITE)
    if not h:
        return Reading("sc580", "狼蛛 SC580", "mouse", status="error",
                       detail="打不开接收器的状态通道", source="sc580")
    data = None
    try:
        for _ in range(max(1, retries)):
            data = _sc580_fetch(h, dev.feat_len)
            if data:
                break
    finally:
        hw.close_handle(h)

    if data and len(data) >= 21 and any(data[8:]):
        level = data[18]
        if 0 < level <= 100:
            model = bytes(data[8:12]).decode("ascii", "ignore")
            fw = bytes(data[24:28]).decode("ascii", "ignore")
            volt = data[15] / 10.0
            _SC580_CACHE.update(level=level, ts=time.time(), model=model, fw=fw)
            remember("sc580", level)
            return Reading("sc580", "狼蛛 SC580", "mouse", level=level, status="ok",
                           source="sc580", updated=time.time(),
                           detail=f"型号 {model}，{volt:.1f}V，固件 {fw}")

    level, ts = cached("sc580")
    if level is not None:
        return Reading("sc580", "狼蛛 SC580", "mouse", level=level,
                       status="cached", source="sc580", updated=ts,
                       detail="接收器这次没回数据，显示上次读数")
    return Reading("sc580", "狼蛛 SC580", "mouse", status="idle", source="sc580",
                   detail="接收器没有响应，检查鼠标是否开机、接收器是否插好")


# ---------------------------------------------------------------------------
# 蓝牙（耳机 / 手机 / 手柄）
# ---------------------------------------------------------------------------
def _kind_from_name(name: str) -> str:
    low = name.lower()
    if any(k in name for k in ("耳机", "耳麦", "Earbuds", "HEADSET", "Headset", "Air")) or "buds" in low:
        return "headset"
    if any(k in low for k in ("redmi", "xiaomi", "mi ", "phone", "k60", "note")) or "手机" in name:
        return "phone"
    if any(k in low for k in ("joystick", "gamepad", "手柄")):
        return "other"
    return "other"


def read_bluetooth() -> list[Reading]:
    out: list[Reading] = []
    try:
        devs = bt_battery.list_bt_devices()
    except Exception:
        return out
    for d in devs:
        if d.battery is None:
            continue
        out.append(Reading(
            key="bt:" + d.instance_id,
            name=d.name or "蓝牙设备",
            kind=_kind_from_name(d.name),
            level=d.battery,
            status="ok",
            source="bluetooth",
            transport="蓝牙",
            updated=time.time(),
            detail="Windows 蓝牙电量属性",
        ))
    return out


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def collect(listen: float = 4.0, include_sc580: bool = True) -> list[Reading]:
    readings = [read_xs98t(listen=listen)]
    if include_sc580:
        readings.append(read_sc580())
    readings.extend(read_bluetooth())
    return readings


if __name__ == "__main__":
    for r in collect(listen=3):
        lvl = f"{r.level}%" if r.level is not None else "—"
        print(f"{r.name:<24} {lvl:>5}  {r.status_text}  {r.detail}")
