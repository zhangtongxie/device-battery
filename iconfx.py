"""托盘图标：粗圆环 + 简化的设备图标（纯几何图形，不用字体字形）。

* 48x48 画布，圆环外径顶满，环宽约 0.16，圆头端点
* 中间图标改成几条线就能画出来的极简形状：键盘=扁圆角框+空格线、鼠标=胶囊+中缝、
  耳机=半环+两侧耳罩、手机=竖圆角框+底部短线
* 形状用 SDF 解析式绘制（每像素直接算覆盖率），比贴字形更锐利，16px 下也认得出
"""
from __future__ import annotations

import ctypes
import math
import winreg
from ctypes import wintypes

import hid_win as hw

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
user32 = ctypes.WinDLL("user32", use_last_error=True)

SIZE = 48
SS = 4
R_OUT = 0.498
R_IN = 0.336
BLUE2 = (56, 150, 236)      # 充电渐变：蓝
GREEN2 = (46, 196, 138)     # 充电渐变：绿
R_CAP = (R_OUT + R_IN) / 2

GLYPH_FILL = 0.80         # 图标占内圆直径的比例
STROKE = 0.115            # 线条半宽（相对图标半宽）

GREEN = (52, 199, 89)
AMBER = (255, 159, 10)
RED = (255, 69, 58)
GREY = (160, 166, 178)


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD),
                ("yHotspot", wintypes.DWORD), ("hbmMask", wintypes.HBITMAP),
                ("hbmColor", wintypes.HBITMAP)]


gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.CreateBitmap.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.c_void_p]
gdi32.CreateBitmap.restype = wintypes.HBITMAP
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
user32.CreateIconIndirect.argtypes = [ctypes.c_void_p]
user32.CreateIconIndirect.restype = wintypes.HICON


def theme_is_light() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return bool(winreg.QueryValueEx(k, "SystemUsesLightTheme")[0])
    except Exception:
        return False


# ---------------------------------------------------------------- SDF 基础
def _sd_box(px, py, hw, hh, r):
    qx = abs(px) - hw + r
    qy = abs(py) - hh + r
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - r


def _sd_seg(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _stroke(d, half, aa):
    """把「到中心线的距离」变成一条带宽度的线。"""
    return max(0.0, min(1.0, 0.5 - (abs(d) - half) / aa))


def _fill(d, aa):
    return max(0.0, min(1.0, 0.5 - d / aa))


# ---------------------------------------------------------------- 极简图标
# 不同形状的「视觉面积」不一样：鼠标是窄高的，按同一坐标画会显得小。
# 这里给每种形状一个放大系数，让它们占满图标框的观感一致。
_GLYPH_SCALE = {
    "keyboard": 0.98,
    "mouse": 1.58,
    "headset": 1.10,
    "phone": 1.16,
    "other": 1.0,
}


def glyph_cov(kind: str, u: float, v: float, aa: float) -> float:
    """u,v ∈ [-1,1]（图标框内），返回覆盖率 0..1。"""
    k = _GLYPH_SCALE.get(kind, 1.0)
    u /= k
    v /= k
    aa /= k
    s = STROKE / k          # 线宽换算回图标坐标，保证各形状观感一致
    if kind == "keyboard":
        body = _sd_box(u, v, 0.94, 0.56, 0.16)
        c = _stroke(body, s, aa)
        bar = _sd_seg(u, v, -0.50, 0.18, 0.50, 0.18)
        return max(c, _stroke(bar, s * 0.80, aa))
    if kind == "mouse":
        body = _sd_box(u, v, 0.38, 0.56, 0.18)
        c = _stroke(body, s, aa)
        slot = _sd_seg(u, v, 0.0, -0.56, 0.0, -0.05)
        return max(c, _stroke(slot, s * 0.80, aa))
    if kind == "headset":
        r = math.hypot(u, v)
        ring = abs(r - 0.70) - s
        band = max(0.0, min(1.0, 0.5 - ring / aa)) * _fill(v - 0.10, aa)
        left = _sd_box(u + 0.56, v - 0.32, 0.16, 0.26, 0.10)
        right = _sd_box(u - 0.56, v - 0.32, 0.16, 0.26, 0.10)
        return max(band, _fill(left, aa), _fill(right, aa))
    if kind == "phone":
        body = _sd_box(u, v, 0.40, 0.76, 0.14)
        c = _stroke(body, s, aa)
        home = _sd_seg(u, v, -0.15, 0.56, 0.15, 0.56)
        return max(c, _stroke(home, s * 0.82, aa))
    r = math.hypot(u, v)
    return _stroke(abs(r - 0.60), s, aa)


def _level_color(level: int | None):
    if level is None:
        return GREY
    if level >= 60:
        return GREEN
    if level >= 30:
        return AMBER
    return RED


_BOLT = [(-0.12, -0.50), (0.28, -0.50), (0.02, -0.06), (0.30, -0.06),
         (-0.22, 0.50), (-0.02, 0.06), (-0.30, 0.06)]


def _bolt_cov(x: float, y: float, scale: float = 1.0) -> float:
    """右下角小闪电（充电中标记）。x/y 是图标坐标（-0.5..0.5）。"""
    s = 0.40 * scale
    bu = (x - 0.27) / s
    bv = (y - 0.27) / s
    inside = False
    j = len(_BOLT) - 1
    for i in range(len(_BOLT)):
        xi, yi = _BOLT[i]
        xj, yj = _BOLT[j]
        if (yi > bv) != (yj > bv):
            x = xi + (bv - yi) * (xj - xi) / (yj - yi)
            if bu < x:
                inside = not inside
        j = i
    return 1.0 if inside else 0.0


def render(level: int | None, kind: str = "other", light: bool = False, size: int = SIZE,
           charging: bool = False) -> bytes:
    pct = 0.0 if level is None else max(0.0, min(100.0, level)) / 100.0
    arc = None if level is None else _level_color(level)
    track = (206, 211, 220) if light else (94, 101, 118)
    glyph_col = (43, 47, 56) if light else (242, 245, 250)

    sweep = pct * 360.0
    half = (R_OUT - R_IN) / 2.0
    pix = 1.0 / size
    step = 1.0 / SS
    half_box = R_IN * GLYPH_FILL          # 图标框半宽（归一化）
    aa = pix / half_box * 1.05            # 一个像素在图标坐标里的宽度

    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            cr = cg = cb = ca = 0.0
            for sy in range(SS):
                for sx in range(SS):
                    fx = (x + (sx + 0.5) * step) * pix - 0.5
                    fy = (y + (sy + 0.5) * step) * pix - 0.5
                    d = math.hypot(fx, fy)
                    col = None
                    if R_IN <= d <= R_OUT:
                        ang = (math.degrees(math.atan2(fy, fx)) + 90.0) % 360.0
                        filled = arc is not None and ang <= sweep
                        if arc is None:
                            col = track
                        elif not filled:
                            col = track
                        elif charging:
                            # 充电：填充弧本身走蓝→绿渐变（弧尾绿、弧头蓝）
                            t = min(1.0, ang / max(1e-6, sweep))
                            col = (int(BLUE2[0] + (GREEN2[0] - BLUE2[0]) * t),
                                   int(BLUE2[1] + (GREEN2[1] - BLUE2[1]) * t),
                                   int(BLUE2[2] + (GREEN2[2] - BLUE2[2]) * t))
                        else:
                            col = arc
                    if arc is not None and 0 < sweep < 360:
                        for a_deg, cap_col in ((0.0, BLUE2 if charging else arc),
                                               (sweep, GREEN2 if charging else arc)):
                            a = math.radians(a_deg - 90.0)
                            if math.hypot(fx - math.cos(a) * R_CAP,
                                          fy - math.sin(a) * R_CAP) <= half:
                                col = cap_col
                                break
                    if col is None:
                        continue
                    cr += col[0]
                    cg += col[1]
                    cb += col[2]
                    ca += 1.0

            n = SS * SS
            a = ca / n
            i = (y * size + x) * 4
            if a > 0:
                out[i] = int(cb / ca)
                out[i + 1] = int(cg / ca)
                out[i + 2] = int(cr / ca)
                out[i + 3] = int(min(1.0, a * 1.1) * 255)

            u = ((x + 0.5) * pix - 0.5) / half_box
            v = ((y + 0.5) * pix - 0.5) / half_box
            g = glyph_cov(kind, u, v, aa)
            if g > 0.01:
                if out[i + 3] == 0:
                    out[i] = glyph_col[2]
                    out[i + 1] = glyph_col[1]
                    out[i + 2] = glyph_col[0]
                else:
                    out[i] = int(out[i] * (1 - g) + glyph_col[2] * g)
                    out[i + 1] = int(out[i + 1] * (1 - g) + glyph_col[1] * g)
                    out[i + 2] = int(out[i + 2] * (1 - g) + glyph_col[0] * g)
                out[i + 3] = max(out[i + 3], int(min(1.0, g * 1.15) * 255))
    return bytes(out)


def to_hicon(bgra: bytes, size: int = SIZE) -> int:
    screen = gdi32.CreateCompatibleDC(None)
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits = ctypes.c_void_p()
    bmp = gdi32.CreateDIBSection(screen, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    ctypes.memmove(bits, bgra, len(bgra))
    mask = gdi32.CreateBitmap(size, size, 1, 1, None)
    info = ICONINFO(True, 0, 0, mask, bmp)
    hicon = user32.CreateIconIndirect(ctypes.byref(info))
    gdi32.DeleteObject(bmp)
    gdi32.DeleteObject(mask)
    gdi32.DeleteDC(screen)
    return hicon


_cache: dict[tuple, int] = {}


def icon_for(level: int | None, kind: str = "other", light: bool | None = None,
             charging: bool = False) -> int:
    if light is None:
        light = theme_is_light()
    key = (level, kind, light, charging)
    if key in _cache:
        return _cache[key]
    hicon = to_hicon(render(level, kind, light, charging=charging))
    _cache[key] = hicon
    return hicon
