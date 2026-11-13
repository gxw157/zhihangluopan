@echo off
setlocal
cd /d "%~dp0"
title 职航罗盘 · 学生职业规划大数据平台

set "PORT=8520"
set "PYEXE=%~dp0.venv\Scripts\python.exe"
set "MIRROR=https://mirrors.aliyun.com/pypi/simple/"

if exist "%PYEXE%" goto chk_deps
goto mk_env

rem ================================================================ 建环境
:mk_env
echo.
echo  [1/3] 首次运行，正在创建运行环境，大约 2 分钟，请不要关闭窗口
echo.
set "BASEPY="
python -c "import sys" >nul 2>nul
if not errorlevel 1 set "BASEPY=python"
if defined BASEPY goto do_venv
py -3 -c "import sys" >nul 2>nul
if not errorlevel 1 set "BASEPY=py -3"
if not defined BASEPY goto no_py

:do_venv
%BASEPY% -m venv ".venv"
if exist "%PYEXE%" goto pip_inst
goto venv_fail

:pip_inst
echo  [2/3] 正在安装依赖，走阿里云镜像，请稍候...
"%PYEXE%" -m pip install -q --upgrade pip -i %MIRROR%
"%PYEXE%" -m pip install -q -r requirements.txt -i %MIRROR%
if errorlevel 1 goto pip_retry
goto chk_deps

:pip_retry
echo  镜像没装成，换官方源再试一次...
"%PYEXE%" -m pip install -q -r requirements.txt
if errorlevel 1 goto pip_fail

rem ================================================================ 查依赖
:chk_deps
"%PYEXE%" -c "import streamlit" >nul 2>nul
if errorlevel 1 goto fix_deps

rem ================================================================ 查数据
if not exist "data\jobs.db" goto no_data

rem ================================================================ 选端口
netstat -ano | findstr /c:":8520 " | findstr /c:"LISTENING" >nul 2>nul
if errorlevel 1 goto start
set "PORT=8521"
netstat -ano | findstr /c:":8521 " | findstr /c:"LISTENING" >nul 2>nul
if errorlevel 1 goto start
set "PORT=8522"

rem ================================================================ 启动
:start
echo.
echo  [3/3] 启动中，浏览器会自动打开  http://localhost:%PORT%
echo        关闭这个窗口就是停止服务。
echo        本机访问   http://localhost:%PORT%
echo        手机访问   同一 WiFi 下打开 http://本机IP:%PORT% （ipconfig 查看）
echo.
"%PYEXE%" -m streamlit run app_all.py --server.port %PORT% --server.address 0.0.0.0 --browser.gatherUsageStats false
echo.
echo  服务已停止。如果页面没自动打开，手动访问 http://localhost:%PORT%
pause
exit /b 0

rem ================================================================ 出错处理
:fix_deps
echo.
echo  运行环境不完整，正在补装依赖...
"%PYEXE%" -m pip install -r requirements.txt -i %MIRROR%
if errorlevel 1 "%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto pip_fail
goto chk_data2

:chk_data2
if not exist "data\jobs.db" goto no_data
goto start

:no_data
echo.
echo  ------------------------------------------------------------
echo   没找到 data\jobs.db，岗位数据库不在。
echo   把 jobs.db 放进 data 目录，或者重跑一次采集（需要联网）：
echo       .venv\Scripts\python.exe -m core.crawl --pages 3
echo   详细说明见 docs\操作手册.md
echo  ------------------------------------------------------------
echo.
pause
exit /b 1

:no_py
echo.
echo  ------------------------------------------------------------
echo   这台电脑上没找到能用的 Python。
echo   1. 打开 https://www.python.org/downloads/ 下载 3.10 以上版本
echo   2. 安装时务必勾选 Add python.exe to PATH
echo   3. 装完重启电脑，再双击本文件
echo  ------------------------------------------------------------
echo.
pause
exit /b 1

:venv_fail
echo.
echo  创建虚拟环境失败。多半是 Python 装得不完整，或者装在了中文路径下。
echo  可以手动执行：python -m venv .venv
echo.
pause
exit /b 1

:pip_fail
echo.
echo  ------------------------------------------------------------
echo   依赖装不上，通常是网络问题。
echo   换个网络（比如手机热点）再双击一次，已经下过的包不会重下。
echo   还是不行就手动执行：
echo       .venv\Scripts\python.exe -m pip install -r requirements.txt -i %MIRROR%
echo   然后把屏幕上的报错发给指导老师。
echo  ------------------------------------------------------------
echo.
pause
exit /b 1
