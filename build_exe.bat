@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 1) 安装打包工具 ===
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :fail

echo.
echo === 2) 生成图标 ===
python make_ico.py

echo.
echo === 3) 打包（文件夹版，最稳，不依赖 %TEMP%） ===
python -m PyInstaller --noconfirm --clean --onedir --noconsole --name "设备电量" --icon app.ico --distpath dist --workpath build main.py
if errorlevel 1 goto :fail

echo.
echo === 4) 打包（单文件版，就地解压，避免 %TEMP% 不可写） ===
python -m PyInstaller --noconfirm --onefile --noconsole --name "设备电量-单文件" --icon app.ico --runtime-tmpdir "." --distpath dist --workpath build main.py

echo.
echo === 5) 压缩文件夹版 ===
powershell -NoProfile -Command "Compress-Archive -Path 'dist\设备电量' -DestinationPath 'dist\设备电量-免解压版.zip' -Force"

echo.
echo 完成：
echo   dist\设备电量\设备电量.exe        （文件夹版，推荐）
echo   dist\设备电量-免解压版.zip        （同上，压缩包）
echo   dist\设备电量-单文件.exe          （单文件，启动时解压到当前目录）
pause
exit /b 0

:fail
echo.
echo 打包失败，检查 Python / 网络（pip 要能访问 PyPI）。
pause
exit /b 1
