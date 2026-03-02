@echo off
REM ============================
REM 一键刷机 + 上传脚本 + 重置 ESP32-S3
REM ============================

REM --- 设置参数 ---
SET PORT=COM5
SET BAUD=460800
SET FIRMWARE=esp32/ESP32_GENERIC_S3-20251209-v1.27.0.bin
SET SCRIPT_FOLDER=esp32

echo.
echo ============================
echo Step 1: 擦除 Flash
echo ============================
python -m esptool --chip esp32s3 --port %PORT% erase_flash
IF ERRORLEVEL 1 (
    echo 擦除 Flash 失败，请检查板子和端口！
    pause
    exit /b 1
)

echo.
echo ============================
echo Step 2: 刷入固件
echo ============================
python flash.py --chip esp32s3 --offset 0x0 --port %PORT% --baud %BAUD% --bin %FIRMWARE%
IF ERRORLEVEL 1 (
    echo 固件刷入失败！
    pause
    exit /b 1
)

echo.
echo ============================
echo Step 3: 清理板子旧脚本文件
echo ============================
for %%f in (%SCRIPT_FOLDER%\*.py) do (
    mpremote connect %PORT% fs rm :/%%~nxf
)
for %%f in (%SCRIPT_FOLDER%\*.json) do (
    mpremote connect %PORT% fs rm :/%%~nxf
)

echo.
echo ============================
echo Step 4: 上传脚本文件
echo ============================
for %%f in (%SCRIPT_FOLDER%\*.py) do (
    mpremote connect %PORT% fs cp %%f :/%%~nxf
)
for %%f in (%SCRIPT_FOLDER%\*.json) do (
    mpremote connect %PORT% fs cp %%f :/%%~nxf
)

echo.
echo ============================
echo Step 5: 重置板子
echo ============================
mpremote connect %PORT% reset

echo.
echo ============================
echo 刷机 + 上传完成！
echo ============================
pause