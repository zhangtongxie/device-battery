@echo off
chcp 65001 >nul
rem 把程序复制到本机目录再启动（也用来更新到新版本）。
rem 为什么要复制：从压缩包/沙箱里直接双击的 exe 可能带 Low 完整性标签，
rem 那样 Windows 会让它低权限运行，托盘图标加不上（Shell_NotifyIcon 错误码 5）。
rem 复制出来的新文件继承目标目录的普通权限，就不需要管理员了。

set TARGET=%LOCALAPPDATA%\DeviceBattery
echo 安装到：%TARGET%
if not exist "%TARGET%" mkdir "%TARGET%"

echo 关掉正在运行的旧版本...
taskkill /IM "设备电量.exe" /F >nul 2>&1
timeout /t 1 >nul

if exist "%~dp0设备电量\设备电量.exe" (
    xcopy "%~dp0设备电量\*" "%TARGET%\" /E /I /Y >nul
) else if exist "%~dp0设备电量.exe" (
    copy /Y "%~dp0设备电量.exe" "%TARGET%\" >nul
) else (
    echo 没找到 设备电量.exe，请把这个脚本放在程序目录里运行。
    pause
    exit /b 1
)

start "" "%TARGET%\设备电量.exe"
echo 已更新并启动：%TARGET%\设备电量.exe
pause
