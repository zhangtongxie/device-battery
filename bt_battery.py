"""Bluetooth device battery via Windows PnP properties (no third-party deps).

Windows stores the battery level of paired Bluetooth / BLE accessories in the
device property ``DEVPKEY_Bluetooth_Battery``
(``{104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2``) — the very value the Settings
app shows.  Reading it needs SetupAPI only.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import hid_win as hw
import bt_conn

setupapi = hw.setupapi

DEVPROP_TYPE_BYTE = 0x00000003
DEVPROP_TYPE_UINT16 = 0x00000007
DEVPROP_TYPE_UINT32 = 0x00000008
DEVPROP_TYPE_STRING = 0x00000012
DEVPROP_TYPE_BOOLEAN = 0x00000011


class DEVPROPKEY(ctypes.Structure):
    _fields_ = [("fmtid", hw.GUID), ("pid", wintypes.ULONG)]


# {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, 2
BLUETOOTH_BATTERY = DEVPROPKEY(
    hw.GUID(0x104EA319, 0x6EE2, 0x4701,
            (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB, 0xF4, 0x25, 0xBB, 0xE5)), 2)

setupapi.SetupDiGetDevicePropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(hw.SP_DEVINFO_DATA), ctypes.POINTER(DEVPROPKEY),
    ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
setupapi.SetupDiGetDevicePropertyW.restype = wintypes.BOOL

BLUETOOTH_CLASS = hw.GUID(0xE0CBF06C, 0xCD8B, 0x4647,
                          (ctypes.c_ubyte * 8)(0xBB, 0x8A, 0x26, 0x3B, 0x43, 0xF0, 0xF9, 0x74))


@dataclass
class BtDevice:
    name: str
    instance_id: str
    battery: int | None = None
    connected: bool = False

    def __str__(self) -> str:
        lvl = f"{self.battery}%" if self.battery is not None else "—"
        return f"{self.name}  {lvl}  {'已连接' if self.connected else '未连接'}"


def _get_prop(devs, devinfo, key, size=512) -> tuple[int, object] | None:
    typ = wintypes.ULONG(0)
    buf = ctypes.create_string_buffer(size)
    need = wintypes.DWORD(0)
    ok = setupapi.SetupDiGetDevicePropertyW(
        devs, ctypes.byref(devinfo), ctypes.byref(key), ctypes.byref(typ),
        buf, size, ctypes.byref(need), 0)
    if not ok:
        return None
    if typ.value in (DEVPROP_TYPE_BYTE, DEVPROP_TYPE_BOOLEAN):
        return typ.value, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))[0]
    if typ.value == DEVPROP_TYPE_UINT16:
        return typ.value, ctypes.cast(buf, ctypes.POINTER(wintypes.USHORT))[0]
    if typ.value == DEVPROP_TYPE_UINT32:
        return typ.value, ctypes.cast(buf, ctypes.POINTER(wintypes.ULONG))[0]
    if typ.value == DEVPROP_TYPE_STRING:
        return typ.value, buf.raw.decode("utf-16-le", "ignore").split("\x00")[0]
    return typ.value, None


def _friendly_name(devs, devinfo) -> str:
    SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC = 0x0C, 0x00
    for prop in (SPDRP_FRIENDLYNAME, SPDRP_DEVICEDESC):
        buf = ctypes.create_string_buffer(512)
        need = wintypes.DWORD(0)
        if setupapi.SetupDiGetDeviceRegistryPropertyW(devs, ctypes.byref(devinfo), prop,
                                                      None, buf, 512, ctypes.byref(need)):
            return buf.raw.decode("utf-16-le", "ignore").split("\x00")[0]
    return ""


def _instance_id(devs, devinfo) -> str:
    buf = ctypes.create_string_buffer(1024)
    need = wintypes.DWORD(0)
    if setupapi.SetupDiGetDeviceInstanceIdW(devs, ctypes.byref(devinfo), buf, 1024,
                                            ctypes.byref(need)):
        return buf.raw.decode("utf-16-le", "ignore").split("\x00")[0]
    return ""


setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(hw.SP_DEVINFO_DATA), wintypes.DWORD,
    ctypes.POINTER(wintypes.ULONG), ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD)]
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(hw.SP_DEVINFO_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]


setupapi.SetupDiEnumDeviceInfo.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(hw.SP_DEVINFO_DATA)]
setupapi.SetupDiEnumDeviceInfo.restype = wintypes.BOOL


def list_bt_devices(connected_only: bool = True) -> list[BtDevice]:
    """Present 的蓝牙设备节点（含电量）。connected_only 时剔除「配对过但没连」的。"""
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(BLUETOOTH_CLASS), None, None, 0x02)
    if devs == hw.INVALID_HANDLE_VALUE or not devs:
        return []
    out: list[BtDevice] = []
    idx = 0
    while True:
        di = hw.SP_DEVINFO_DATA()
        di.cbSize = ctypes.sizeof(di)
        if not setupapi.SetupDiEnumDeviceInfo(devs, idx, ctypes.byref(di)):
            break
        idx += 1
        iid = _instance_id(devs, di)
        name = _friendly_name(devs, di)
        dev = BtDevice(name=name, instance_id=iid, connected=True)
        got = _get_prop(devs, di, BLUETOOTH_BATTERY)
        if got and isinstance(got[1], int) and 0 <= got[1] <= 100:
            dev.battery = got[1]
        out.append(dev)
    setupapi.SetupDiDestroyDeviceInfoList(devs)

    if connected_only:
        addrs = {d.instance_id: bt_conn.address_from_instance(d.instance_id) for d in out
                 if d.battery is not None}
        wanted = [a for a in addrs.values() if a]
        if wanted:
            state = bt_conn.connected_map(wanted)
            keep = []
            for d in out:
                addr = addrs.get(d.instance_id)
                if addr and addr in state and not state[addr]:
                    continue
                d.connected = bool(state.get(addr, True)) if addr else True
                keep.append(d)
            out = keep
    return out


if __name__ == "__main__":
    for d in list_bt_devices():
        print(d)
