"""后台监听：键盘的省电推送不定时，所以常驻监听 + 缓存最后一次电量。"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import hid_win as hw
import protocols as P
import bt_battery


@dataclass
class Snapshot:
    readings: list[P.Reading] = field(default_factory=list)
    ts: float = 0.0


class Monitor:
    """常驻后台线程：键盘通道 + 蓝牙轮询。"""

    def __init__(self, bt_interval: float = 30.0, kbd_retry: float = 3.0,
                 mouse_interval: float = 5.0, show_bt: bool = True,
                 disabled: set[str] | None = None):
        self.bt_interval = bt_interval
        self.kbd_retry = kbd_retry
        self.mouse_interval = mouse_interval
        self.show_bt = show_bt
        self.disabled: set[str] = set(disabled or ())
        self.known: dict[str, str] = {}
        self._lock = threading.Lock()
        self._kbd = P.Reading("xs98t", "GANSS XS98T", "keyboard", status="idle",
                              detail="正在监听…", source="xs98t")
        self._kbd_level: int | None = None
        self._kbd_ts = 0.0
        self._bt: list[P.Reading] = []
        self._bt_ts = 0.0
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self.sc580 = P.read_sc580()

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> "Monitor":
        for fn in (self._kbd_loop, self._bt_loop, self._mouse_loop):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def stop(self) -> None:
        self._stop.set()

    def refresh_now(self) -> None:
        """立刻重扫蓝牙，并戳一下键盘/鼠标接收器。"""
        P._poke(None)
        try:
            self.sc580 = P.read_sc580()
        except Exception:
            pass
        try:
            self._bt = P.read_bluetooth()
            self._bt_ts = time.time()
        except Exception:
            pass

    # -- data --------------------------------------------------------------
    def snapshot(self) -> Snapshot:
        with self._lock:
            kbd = P.Reading(**{**self._kbd.__dict__})
            kbd.raw = list(self._kbd.raw)
            bt = [P.Reading(**{**r.__dict__}) for r in self._bt]
        if self._kbd_level is not None:
            kbd.level = self._kbd_level
            kbd.updated = self._kbd_ts
            kbd.status = "ok"
            kbd.detail = "0x20 状态帧（键盘推送）"
            if kbd.age > 120:
                kbd.status = "cached"
                kbd.detail = "键盘休眠，下面是最后一次读到的电量；按任意键或打开官方驱动软件可更新"
        else:
            level, ts = P.cached("xs98t")
            if level is not None:
                kbd.level, kbd.updated, kbd.status = level, ts, "cached"
                kbd.detail = "键盘休眠，显示上次读数；按任意键或打开官方驱动软件可更新"
        out = [kbd, self.sc580] + (bt if self.show_bt else [])
        for r in out:
            self.known[r.key] = r.name
        out = [r for r in out if r.key not in self.disabled]
        return Snapshot(readings=out, ts=time.time())

    def known_devices(self) -> dict[str, str]:
        """见过的设备（key -> 名字），用于设置里的列表。"""
        with self._lock:
            return dict(self.known)

    # -- keyboard ----------------------------------------------------------
    def _kbd_loop(self) -> None:
        while not self._stop.is_set():
            dev = P.find_xs98t()
            if not dev:
                self._set_kbd_status("offline", "没有找到 05AC:024F 的 2.4G 接收器")
                self._stop.wait(self.kbd_retry)
                continue
            h = hw.open_device(dev.path, hw.GENERIC_READ, overlapped=True)
            if not h:
                self._set_kbd_status("error", "打不开接收器的电量通道")
                self._stop.wait(self.kbd_retry)
                continue
            try:
                while not self._stop.is_set():
                    data = hw.read_report(h, dev.in_len, timeout_ms=500)
                    if data is None:
                        if self._kbd_level is None:
                            self._set_kbd_status("idle", "键盘休眠：按任意键、或打开官方驱动软件后才会推送电量")
                        continue
                    self._handle_frame(data)
            finally:
                hw.close_handle(h)
            self._stop.wait(self.kbd_retry)

    def _handle_frame(self, data: bytes) -> None:
        if not P._checksum_ok(data) or len(data) < 6:
            return
        if data[1] != P.FRAME_BATTERY:
            return
        level = data[4]
        if not (0 <= level <= 100):
            return
        # 键盘不做充电推断：它的固件/官方驱动都没有充电指示，电量变了就是真的变了
        P.remember("xs98t", level)
        with self._lock:
            self._kbd_level = level
            self._kbd_ts = time.time()
            self._kbd.level = level
            self._kbd.updated = self._kbd_ts
            self._kbd.status = "ok"
            self._kbd.detail = "0x20 状态帧（键盘推送）"
            self._kbd.raw = (self._kbd.raw + [data.hex(" ")])[-8:]

    def _set_kbd_status(self, status: str, detail: str) -> None:
        with self._lock:
            self._kbd.status = status
            self._kbd.detail = detail

    # -- mouse -------------------------------------------------------------
    def _mouse_loop(self) -> None:
        # 被用户在设置里关掉的设备就不再轮询，省得一直戳接收器
        while not self._stop.is_set():
            if "sc580" in self.disabled:
                self._stop.wait(1.0)
                continue
            try:
                self.sc580 = P.read_sc580()
            except Exception:
                pass
            self._stop.wait(max(1.0, float(self.mouse_interval)))

    # -- bluetooth ---------------------------------------------------------
    def _bt_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._bt = P.read_bluetooth()
                self._bt_ts = time.time()
            except Exception:
                pass
            self._stop.wait(self.bt_interval)


if __name__ == "__main__":
    m = Monitor().start()
    for _ in range(6):
        snap = m.snapshot()
        print(time.strftime("%H:%M:%S"))
        for r in snap.readings:
            lvl = f"{r.level}%" if r.level is not None else "—"
            print(f"   {r.name:<22} {lvl:>5}  {r.status_text}  {r.detail}")
        time.sleep(2)
    m.stop()
