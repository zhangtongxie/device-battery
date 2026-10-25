"""Minimal Windows HID layer built on ctypes (stdlib only).

Concepts
--------
* A *collection* (interface path) is what SetupAPI enumerates, e.g.
  ``\\\\?\\hid#vid_248a&pid_5b2f&mi_02#...#{4d1e55b2-...}``.
* Every collection has a top-level UsagePage/Usage and report lengths.
* Reading input reports must happen on a handle opened with FILE_FLAG_OVERLAPPED,
  otherwise a stuck ReadFile blocks the thread forever.
"""
from __future__ import annotations

import ctypes
import re
import time
from ctypes import wintypes
from dataclasses import dataclass, field

setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]

    def __str__(self) -> str:  # {XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX}
        d4 = bytes(self.Data4)
        return "{%08X-%04X-%04X-%s-%s}" % (
            self.Data1, self.Data2, self.Data3, d4[:2].hex().upper(), d4[2:].hex().upper())


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("InterfaceClassGuid", GUID),
                ("Flags", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class SP_DEVINFO_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("ClassGuid", GUID),
                ("DevInst", wintypes.DWORD), ("Reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wintypes.ULONG), ("VendorID", wintypes.USHORT),
                ("ProductID", wintypes.USHORT), ("VersionNumber", wintypes.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [("Usage", wintypes.USHORT), ("UsagePage", wintypes.USHORT),
                ("InputReportByteLength", wintypes.USHORT),
                ("OutputReportByteLength", wintypes.USHORT),
                ("FeatureReportByteLength", wintypes.USHORT),
                ("Reserved", wintypes.USHORT * 17),
                ("NumberLinkCollectionNodes", wintypes.USHORT),
                ("NumberInputButtonCaps", wintypes.USHORT),
                ("NumberInputValueCaps", wintypes.USHORT),
                ("NumberInputDataIndices", wintypes.USHORT),
                ("NumberOutputButtonCaps", wintypes.USHORT),
                ("NumberOutputValueCaps", wintypes.USHORT),
                ("NumberOutputDataIndices", wintypes.USHORT),
                ("NumberFeatureButtonCaps", wintypes.USHORT),
                ("NumberFeatureValueCaps", wintypes.USHORT),
                ("NumberFeatureDataIndices", wintypes.USHORT)]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.argtypes = [wintypes.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wintypes.BOOL
hid.HidD_GetProductString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetManufacturerString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetSerialNumberString.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetPreparsedData.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wintypes.LONG
hid.HidD_GetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_GetFeature.restype = wintypes.BOOL
hid.HidD_SetFeature.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.ULONG]
hid.HidD_SetFeature.restype = wintypes.BOOL
hid.HidD_FlushQueue.argtypes = [wintypes.HANDLE]
hid.HidD_FlushQueue.restype = wintypes.BOOL

setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wintypes.LPCWSTR,
                                         wintypes.HWND, wintypes.DWORD]
setupapi.SetupDiGetClassDevsW.restype = wintypes.HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wintypes.DWORD,
    ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiEnumDeviceInterfaces.restype = wintypes.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wintypes.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wintypes.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wintypes.HANDLE]

kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateEventW.restype = wintypes.HANDLE
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                         ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]

HIDP_STATUS_SUCCESS = 0x00110000


@dataclass
class HidDevice:
    path: str
    vid: str | None = None
    pid: str | None = None
    mi: str | None = None
    product: str = ""
    manufacturer: str = ""
    serial: str = ""
    usage_page: int = 0
    usage: int = 0
    in_len: int = 0
    out_len: int = 0
    feat_len: int = 0
    error: int | None = None
    extra: dict = field(default_factory=dict)

    @property
    def id(self) -> str:
        return f"{self.vid or '????'}:{self.pid or '????'}"

    @property
    def label(self) -> str:
        return self.product or self.id

    def __str__(self) -> str:
        return (f'{self.id} mi={self.mi or "-"} up={self.usage_page:04X}/{self.usage:04X} '
                f'in={self.in_len} out={self.out_len} feat={self.feat_len} "{self.product}"')


def _wstr(fn, handle) -> str:
    buf = ctypes.create_unicode_buffer(256)
    if fn(handle, buf, ctypes.sizeof(buf)):
        return buf.value
    return ""


def open_device(path: str, access: int = 0, overlapped: bool = False) -> int | None:
    flags = FILE_FLAG_OVERLAPPED if overlapped else 0
    h = kernel32.CreateFileW(path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
                             None, OPEN_EXISTING, flags, None)
    if h == INVALID_HANDLE_VALUE or not h:
        return None
    return h


def close_handle(h) -> None:
    if h and h != INVALID_HANDLE_VALUE:
        kernel32.CloseHandle(h)


def enumerate_hid() -> list[HidDevice]:
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(guid), None, None,
                                         DIGCF_PRESENT | DIGCF_DEVICEINTERFACE)
    out: list[HidDevice] = []
    idx = 0
    while True:
        did = SP_DEVICE_INTERFACE_DATA()
        did.cbSize = ctypes.sizeof(did)
        if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(guid), idx,
                                                    ctypes.byref(did)):
            break
        req = wintypes.DWORD(0)
        setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(did), None, 0,
                                                  ctypes.byref(req), None)
        buf = ctypes.create_string_buffer(max(req.value, 2048))
        ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0] = 8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
        devinfo = SP_DEVINFO_DATA()
        devinfo.cbSize = ctypes.sizeof(devinfo)
        if setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(did), buf, len(buf),
                                                     ctypes.byref(req), ctypes.byref(devinfo)):
            path = buf.raw[4:].decode("utf-16-le", "ignore").split("\x00")[0]
            out.append(_describe(path))
        idx += 1
    setupapi.SetupDiDestroyDeviceInfoList(devs)
    return out


def _describe(path: str) -> HidDevice:
    d = HidDevice(path=path)
    m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path)
    if m:
        d.vid, d.pid = m.group(1), m.group(2)
    mm = re.search(r"&mi_([0-9a-f]{2})", path)
    if mm:
        d.mi = mm.group(1)
    h = open_device(path, 0)
    if not h:
        d.error = ctypes.get_last_error()
        return d
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(attrs)
        if hid.HidD_GetAttributes(h, ctypes.byref(attrs)):
            d.vid = "%04x" % attrs.VendorID
            d.pid = "%04x" % attrs.ProductID
            d.extra["ver"] = "%04x" % attrs.VersionNumber
        d.product = _wstr(hid.HidD_GetProductString, h)
        d.manufacturer = _wstr(hid.HidD_GetManufacturerString, h)
        d.serial = _wstr(hid.HidD_GetSerialNumberString, h)
        pp = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(h, ctypes.byref(pp)):
            caps = HIDP_CAPS()
            if hid.HidP_GetCaps(pp, ctypes.byref(caps)) == HIDP_STATUS_SUCCESS:
                d.usage_page = caps.UsagePage
                d.usage = caps.Usage
                d.in_len = caps.InputReportByteLength
                d.out_len = caps.OutputReportByteLength
                d.feat_len = caps.FeatureReportByteLength
            hid.HidD_FreePreparsedData(pp)
    finally:
        close_handle(h)
    return d


# --------------------------------------------------------------------------- reports


def get_feature(h, report_id: int, length: int) -> bytes | None:
    buf = ctypes.create_string_buffer(max(length, 2))
    ctypes.cast(buf, ctypes.POINTER(wintypes.BYTE))[0] = report_id
    if hid.HidD_GetFeature(h, buf, len(buf)):
        return buf.raw
    return None


def set_feature(h, data: bytes) -> bool:
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    return bool(hid.HidD_SetFeature(h, buf, len(data)))


def write_report(h, data: bytes) -> bool | None:
    """WriteFile on an output report. Returns None when the write did not complete."""
    written = wintypes.DWORD(0)
    buf = ctypes.create_string_buffer(bytes(data), len(data))
    ok = kernel32.WriteFile(h, buf, len(data), ctypes.byref(written), None)
    if not ok:
        return None
    return True


def read_report(h, length: int, timeout_ms: int = 1000) -> bytes | None:
    """Read one input report from a handle opened with FILE_FLAG_OVERLAPPED."""
    ov = OVERLAPPED()
    event = kernel32.CreateEventW(None, True, False, None)
    ov.hEvent = event
    buf = ctypes.create_string_buffer(length)
    nread = wintypes.DWORD(0)
    t0 = time.perf_counter()
    try:
        ok = kernel32.ReadFile(h, buf, length, ctypes.byref(nread), ctypes.byref(ov))
        if not ok:
            err = ctypes.get_last_error()
            if err != 997:  # ERROR_IO_PENDING
                return None
            rc = kernel32.WaitForSingleObject(event, timeout_ms)
            if rc != 0:  # WAIT_OBJECT_0
                kernel32.CancelIoEx(h, ctypes.byref(ov))
                return None
            if not kernel32.GetOverlappedResult(h, ctypes.byref(ov), ctypes.byref(nread), False):
                return None
        return buf.raw[:nread.value]
    finally:
        kernel32.CloseHandle(event)


def drain(h, length: int, timeout_ms: int = 0) -> list[bytes]:
    """Collect already-queued input reports."""
    out = []
    while True:
        d = read_report(h, length, timeout_ms)
        if d is None:
            break
        out.append(d)
        if not timeout_ms:
            break
    return out


if __name__ == "__main__":
    for d in enumerate_hid():
        print(d)
