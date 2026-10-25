"""蓝牙连接状态（Windows 只在 WinRT 里暴露，Python 拿不到，只能借一次 powershell）。

配对过但没连的设备，PnP 里照样在、电量属性也是上次的缓存 —— 所以必须单独问
``BluetoothLEDevice.ConnectionStatus``。结果缓存 20 秒，PowerShell 不可用时按「已连接」
处理（fail-open，宁可多显示也不要漏）。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import time

_TTL = 20.0
_cache: dict[str, tuple[bool, float]] = {}
_script_path: str | None = None

_PS = r"""
param([Parameter(ValueFromRemainingArguments=$true)]$addrs)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Devices.Bluetooth.BluetoothLEDevice,Windows.Devices.Bluetooth,ContentType=WindowsRuntime] | Out-Null
$m = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
        $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
        $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
foreach ($a in $addrs) {
  try {
    $addr = [uint64]("0x" + $a)
    $op = [Windows.Devices.Bluetooth.BluetoothLEDevice]::FromBluetoothAddressAsync($addr)
    $t = $m.MakeGenericMethod([Windows.Devices.Bluetooth.BluetoothLEDevice]).Invoke($null, @($op))
    if ($t.Wait(2000)) {
      $d = $t.Result
      if ($d) { Write-Output ("{0} {1}" -f $a, $d.ConnectionStatus) }
    }
  } catch { }
}
"""


def _ensure_script() -> str:
    global _script_path
    if _script_path and os.path.exists(_script_path):
        return _script_path
    fd, path = tempfile.mkstemp(suffix=".ps1", prefix="bt_conn_")
    with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
        f.write(_PS)
    _script_path = path
    return path


def address_from_instance(instance_id: str) -> str | None:
    m = re.search(r"dev_([0-9a-f]{12})", instance_id or "", re.I)
    return m.group(1).lower() if m else None


def connected_map(addresses: list[str]) -> dict[str, bool]:
    """返回 {地址: 是否已连接}；查询失败时返回空字典。"""
    now = time.time()
    todo = [a for a in addresses if a not in _cache or now - _cache[a][1] > _TTL]
    if todo:
        try:
            path = _ensure_script()
            flags = 0x08000000 if os.name == "nt" else 0     # CREATE_NO_WINDOW
            out = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path, *todo],
                capture_output=True, text=True, timeout=20, creationflags=flags)
            for line in (out.stdout or "").splitlines():
                parts = line.strip().split()
                if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{12}", parts[0]):
                    _cache[parts[0]] = (parts[1] == "Connected", now)
        except Exception:
            pass
    return {a: _cache[a][0] for a in addresses if a in _cache}
