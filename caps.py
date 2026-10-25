"""HID value caps：每个接口定义了哪些 Report ID、哪些 usage、多少位。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

import hid_win as hw

hid = hw.hid
HIDP_INPUT, HIDP_OUTPUT, HIDP_FEATURE = 0, 1, 2
HIDP_STATUS_SUCCESS = 0x00110000


class HIDP_RANGE(ctypes.Structure):
    _fields_ = [("UsageMin", wintypes.USHORT), ("UsageMax", wintypes.USHORT),
                ("StringMin", wintypes.USHORT), ("StringMax", wintypes.USHORT),
                ("DesignatorMin", wintypes.USHORT), ("DesignatorMax", wintypes.USHORT),
                ("DataIndexMin", wintypes.USHORT), ("DataIndexMax", wintypes.USHORT)]


class HIDP_NOTRANGE(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("Reserved1", wintypes.USHORT),
                ("StringIndex", wintypes.USHORT), ("Reserved2", wintypes.USHORT),
                ("DesignatorIndex", wintypes.USHORT), ("Reserved3", wintypes.USHORT),
                ("DataIndex", wintypes.USHORT), ("Reserved4", wintypes.USHORT)]


class HIDP_UNION(ctypes.Union):
    _fields_ = [("Range", HIDP_RANGE), ("NotRange", HIDP_NOTRANGE)]


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wintypes.USHORT), ("ReportID", ctypes.c_ubyte),
                ("IsAlias", ctypes.c_ubyte), ("BitField", wintypes.USHORT),
                ("LinkCollection", wintypes.USHORT), ("LinkUsage", wintypes.USHORT),
                ("LinkUsagePage", wintypes.USHORT), ("IsRange", ctypes.c_ubyte),
                ("IsStringRange", ctypes.c_ubyte), ("IsDesignatorRange", ctypes.c_ubyte),
                ("IsAbsolute", ctypes.c_ubyte), ("HasNull", ctypes.c_ubyte),
                ("Reserved", ctypes.c_ubyte), ("BitSize", wintypes.USHORT),
                ("ReportCount", wintypes.USHORT), ("Reserved2", wintypes.USHORT * 5),
                ("UnitsExp", wintypes.ULONG), ("Units", wintypes.ULONG),
                ("LogicalMin", wintypes.LONG), ("LogicalMax", wintypes.LONG),
                ("PhysicalMin", wintypes.LONG), ("PhysicalMax", wintypes.LONG),
                ("u", HIDP_UNION)]


class HIDP_BUTTON_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wintypes.USHORT), ("ReportID", ctypes.c_ubyte),
                ("IsAlias", ctypes.c_ubyte), ("BitField", wintypes.USHORT),
                ("LinkCollection", wintypes.USHORT), ("LinkUsage", wintypes.USHORT),
                ("LinkUsagePage", wintypes.USHORT), ("IsRange", ctypes.c_ubyte),
                ("IsStringRange", ctypes.c_ubyte), ("IsDesignatorRange", ctypes.c_ubyte),
                ("IsAbsolute", ctypes.c_ubyte), ("ReportCount", wintypes.USHORT),
                ("Reserved2", wintypes.USHORT * 9), ("u", HIDP_UNION)]


hid.HidP_GetValueCaps.argtypes = [wintypes.INT, ctypes.c_void_p,
                                  ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetValueCaps.restype = wintypes.LONG
hid.HidP_GetButtonCaps.argtypes = [wintypes.INT, ctypes.c_void_p,
                                   ctypes.POINTER(wintypes.USHORT), ctypes.c_void_p]
hid.HidP_GetButtonCaps.restype = wintypes.LONG


def dump(dev) -> None:
    h = hw.open_device(dev.path, 0)
    if not h:
        print(f"  {dev.id} mi={dev.mi}: 打不开（可能被系统独占）")
        return
    try:
        pp = ctypes.c_void_p()
        if not hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
            return
        print(f"\n### {dev}")
        for rtype, label in ((HIDP_INPUT, "input"), (HIDP_OUTPUT, "output"),
                             (HIDP_FEATURE, "feature")):
            n = wintypes.USHORT(0)
            hid.HidP_GetValueCaps(rtype, None, ctypes.byref(n), pp)
            if n.value:
                cap = n.value + 16          # 缓冲区给足：给少了 hid.dll 会写越界
                arr = (HIDP_VALUE_CAPS * cap)()
                cnt = wintypes.USHORT(cap)
                if hid.HidP_GetValueCaps(rtype, arr, ctypes.byref(cnt), pp) == HIDP_STATUS_SUCCESS:
                    for c in arr[:cnt.value]:
                        usage = (f"{c.u.Range.UsageMin:04X}-{c.u.Range.UsageMax:04X}"
                                 if c.IsRange else f"{c.u.NotRange.Usage:04X}")
                        print(f"  {label:7s} rid={c.ReportID:02X} page={c.UsagePage:04X} "
                              f"usage={usage} bits={c.BitSize} count={c.ReportCount} "
                              f"logical={c.LogicalMin}..{c.LogicalMax}")
            nb = wintypes.USHORT(0)
            hid.HidP_GetButtonCaps(rtype, None, ctypes.byref(nb), pp)
            if nb.value:
                bcap = nb.value + 16
                arr = (HIDP_BUTTON_CAPS * bcap)()
                bcnt = wintypes.USHORT(bcap)
                if hid.HidP_GetButtonCaps(rtype, arr, ctypes.byref(bcnt), pp) == HIDP_STATUS_SUCCESS:
                    for c in arr[:bcnt.value]:
                        print(f"  {label:7s} rid={c.ReportID:02X} page={c.UsagePage:04X} "
                              f"buttons={c.ReportCount}")
        hid.HidD_FreePreparsedData(pp)
    finally:
        hw.close_handle(h)


if __name__ == "__main__":
    import sys
    spec = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    for d in hw.enumerate_hid():
        if spec in f"{d.vid}:{d.pid}".lower():
            dump(d)
