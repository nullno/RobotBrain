@echo off
setlocal enableextensions
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

REM ============================
REM 一键擦除 / 刷固件 / 上传脚本 / 重启 ESP32-S3
REM 可通过第 1 个参数覆盖串口号：install.bat COM7
REM ============================

pushd "%~dp0"

REM --- 默认参数（可在运行前改）---
set "PORT=COM5"
if not "%~1"=="" set "PORT=%~1"
set "BAUD=460800"
set "FIRMWARE=esp32\ESP32_GENERIC_S3-20251209-v1.27.0.bin"
set "SCRIPT_FOLDER=esp32"
set "FLASH_SCRIPT=flash.py"

echo.
echo ============================
echo 检查依赖与文件
echo ============================
where python >nul 2>&1 || (echo 未找到 python，請先安裝 Python 3 並加入 PATH & goto :error)
where mpremote >nul 2>&1 || (echo 未找到 mpremote，請先安裝：python -m pip install mpremote & goto :error)
if not exist "%FLASH_SCRIPT%" (echo 缺少刷机脚本 %FLASH_SCRIPT% & goto :error)
if not exist "%FIRMWARE%" (echo 找不到固件文件 %FIRMWARE% & goto :error)
if not exist "%SCRIPT_FOLDER%" (echo 找不到脚本目录 %SCRIPT_FOLDER% & goto :error)

echo.
echo ============================
echo Step 1: 擦除 Flash
echo ============================
python -m esptool --chip esp32s3 --port %PORT% erase_flash
IF ERRORLEVEL 1 (
    echo 擦除 Flash 失败，请检查板子和端口！
    goto :error
)

echo.
echo ============================
echo Step 2: 刷入固件
echo ============================
python "%FLASH_SCRIPT%" --chip esp32s3 --offset 0x0 --port %PORT% --baud %BAUD% --bin "%FIRMWARE%"
IF ERRORLEVEL 1 (
    echo 固件刷入失败！
    goto :error
)

echo.
echo ============================
echo Step 3: 清理板子旧脚本文件
echo ============================
for %%f in ("%SCRIPT_FOLDER%\*.py") do (
    if exist "%%~f" mpremote connect %PORT% fs rm :/%%~nxf >nul 2>&1
)
for %%f in ("%SCRIPT_FOLDER%\*.json") do (
    if exist "%%~f" mpremote connect %PORT% fs rm :/%%~nxf >nul 2>&1
)

echo.
echo ============================
echo Step 4: 上传脚本文件
echo ============================
for %%f in ("%SCRIPT_FOLDER%\*.py") do (
    if exist "%%~f" mpremote connect %PORT% fs cp "%%~f" :/%%~nxf
)
for %%f in ("%SCRIPT_FOLDER%\*.json") do (
    if exist "%%~f" mpremote connect %PORT% fs cp "%%~f" :/%%~nxf
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
popd
goto :eof

:error
pause
popd
exit /b 1