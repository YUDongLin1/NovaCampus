@echo off
REM 本文件必须保持 ANSI/GBK 编码 + CRLF 换行。cmd.exe 读 UTF-8 批处理时字节偏移会漂移，
REM 中文行会被从中间截断当命令执行；LF 换行会让括号块和 :标签 解析失败。别用 UTF-8 另存。
setlocal EnableExtensions
cd /d "%~dp0"

if not defined WEEKLY_PORT set "WEEKLY_PORT=18080"
if not defined APP_PORT    set "APP_PORT=8900"
set "ROOT=%CD%"

echo ==============================================
echo   NovaCampus / 智枢 Agent  一键启动
echo   周报 MCP:  http://127.0.0.1:%WEEKLY_PORT%/mcp
echo   主服务:    http://127.0.0.1:%APP_PORT%
echo ==============================================
echo.

REM ---------- 1) curl 必需（用来探测服务是否就绪） ----------
where curl >nul 2>nul
if errorlevel 1 (
    echo [X] 找不到 curl.exe，Win10 1803 及以上自带，可能被系统精简了。
    goto :fail
)

REM ---------- 2) 配置文件与模型 Key ----------
if not exist "novaagent\.env" (
    if not exist "novaagent\.env.example" (
        echo [X] 既没有 novaagent\.env 也没有 .env.example
        goto :fail
    )
    copy /y "novaagent\.env.example" "novaagent\.env" >nul
    echo [!] 已生成 novaagent\.env，正在用记事本打开。
    echo     填入 LLM_API_KEY / EMBEDDING_API_KEY 保存后，重新双击本脚本。
    start notepad "%ROOT%\novaagent\.env"
    goto :fail
)

call :key_filled LLM_API_KEY
if errorlevel 1 goto :key_empty
call :key_filled EMBEDDING_API_KEY
if errorlevel 1 goto :key_empty

REM ---------- 3) 已经在跑就不重复启动 ----------
call :port_busy %APP_PORT%
set "APP_UP=%errorlevel%"
call :port_busy %WEEKLY_PORT%
set "WK_UP=%errorlevel%"

if "%APP_UP%"=="1" if "%WK_UP%"=="1" (
    echo [=] 两个服务都已经在运行，直接用浏览器访问：
    echo     http://127.0.0.1:%APP_PORT%
    echo     想重启请先关掉那两个服务窗口。
    goto :end
)
if "%APP_UP%"=="1" goto :port_conflict
if "%WK_UP%"=="1" goto :port_conflict

REM ---------- 4) 虚拟环境 ----------
REM 两个 venv 都能跑就直接用自带的 python 启动，全程不需要 uv。
REM 只有 venv 坏了（比如从别的机器拷来、解释器路径失效）才需要 uv 重建。
set "WKPY=%ROOT%\mcp\weekly\.venv\Scripts\python.exe"
set "APPY=%ROOT%\novaagent\.venv\Scripts\python.exe"

call :venv_ok "%WKPY%"
set "WK_OK=%errorlevel%"
call :venv_ok "%APPY%"
set "APP_OK=%errorlevel%"

if not "%WK_OK%"=="0" goto :bootstrap
if not "%APP_OK%"=="0" goto :bootstrap
goto :launch

:bootstrap
echo [*] 有虚拟环境不可用，需要 uv 重建...
call :find_uv
if not defined UV goto :no_uv
echo     使用 uv: %UV%

call :fix_venv "mcp\weekly" weekly
if errorlevel 1 (
    echo [X] mcp\weekly 重建/装依赖失败
    goto :fail
)
call :fix_venv "novaagent" sync
if errorlevel 1 (
    echo [X] novaagent 重建/装依赖失败
    goto :fail
)

:launch
REM ---------- 5) 先起周报 MCP（主服务启动时要连它，连不上主服务就起不来） ----------
echo [*] 启动周报 MCP 服务（新窗口，别关）...
start "NovaCampus-weekly-MCP" /D "%ROOT%\mcp\weekly" cmd /k "title NovaCampus-weekly-MCP&& set WEEKLY_PORT=%WEEKLY_PORT%&& set WEEKLY_HOST=127.0.0.1&& set NO_PROXY=127.0.0.1,localhost&& .venv\Scripts\python.exe server.py"

call :wait_mcp %WEEKLY_PORT%
if errorlevel 1 (
    echo [X] 周报 MCP 在 %WEEKLY_PORT% 起不来，去看那个窗口的报错。
    goto :fail
)
echo [+] 周报 MCP 就绪

REM ---------- 6) 再起主服务 ----------
echo [*] 启动主服务（新窗口，别关）...
start "NovaCampus-main-app" /D "%ROOT%\novaagent" cmd /k "title NovaCampus-main-app&& set NO_PROXY=127.0.0.1,localhost&& .venv\Scripts\python.exe -m uvicorn novaagent.main:app --host 127.0.0.1 --port %APP_PORT%"

call :wait_http %APP_PORT% 200
if errorlevel 1 (
    echo [X] 主服务起不来，去看那个窗口的报错。
    echo     常见原因：模型 Key 无效，或连不上 http://127.0.0.1:%WEEKLY_PORT%/mcp
    goto :fail
)

REM ---------- 7) 打开浏览器 ----------
echo [+] 主服务就绪，正在打开浏览器...
start "" "http://127.0.0.1:%APP_PORT%"
echo.
echo   演示账号（仅本地演示用）：
echo     student   / student123    学生
echo     counselor / counselor123  辅导员（功能最全）
echo     admin     / admin123      校管理员
echo.
echo   停止服务：关掉 NovaCampus-weekly-MCP 和 NovaCampus-main-app 两个窗口。
goto :end


REM ================= 子过程 =================
:key_filled
findstr /r /c:"^%~1=..*" "novaagent\.env" >nul 2>nul
exit /b %errorlevel%

:port_busy
REM %~1=端口。只要有 HTTP 应答（哪怕 404/400）就说明该端口已被占用，返回 1
for /f "usebackq delims=" %%c in (`curl -s -o nul -w "%%{http_code}" --noproxy 127.0.0.1 --max-time 3 "http://127.0.0.1:%~1/" 2^>nul`) do (
    if not "%%c"=="000" exit /b 1
)
exit /b 0

:venv_ok
REM %~1=python.exe 绝对路径。返回 0=可用 1=不可用
"%~1" -c "import uvicorn, mcp" >nul 2>nul
if errorlevel 1 exit /b 1
exit /b 0

:find_uv
REM 双击运行时的 cmd 可能看不到 Git Bash 里的 PATH，所以要挨个试常见安装位置
set "UV="
for /f "delims=" %%p in ('where uv 2^>nul') do if not defined UV set "UV=%%p"
if defined UV exit /b 0
if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if defined UV exit /b 0
if exist "%LOCALAPPDATA%\Programs\uv\uv.exe" set "UV=%LOCALAPPDATA%\Programs\uv\uv.exe"
if defined UV exit /b 0
if exist "%ProgramFiles%\uv\uv.exe" set "UV=%ProgramFiles%\uv\uv.exe"
exit /b 0

:fix_venv
REM %~1=项目相对目录  %~2=weekly 或 sync
set "VP=%ROOT%\%~1\.venv\Scripts\python.exe"
call :venv_ok "%VP%"
if not errorlevel 1 exit /b 0
echo     [!] %~1\.venv 不可用，正在重建（旧目录留成 venv.broken）
if exist "%ROOT%\%~1\venv.broken" rmdir /s /q "%ROOT%\%~1\venv.broken"
if exist "%ROOT%\%~1\.venv" ren "%ROOT%\%~1\.venv" "venv.broken"
pushd "%ROOT%\%~1"
call "%UV%" venv --python 3.12 .venv >nul
if errorlevel 1 (
    popd
    exit /b 1
)
if "%~2"=="weekly" (
    call "%UV%" pip install --quiet --python ".venv\Scripts\python.exe" "mcp==2.2.0"
) else (
    call "%UV%" sync --quiet
)
set "RC=%errorlevel%"
popd
exit /b %RC%

:wait_mcp
REM %~1=端口。/mcp 只收握手请求，进程活着就返回 400，所以任意非 000 即就绪
for /l %%i in (1,1,60) do (
    for /f "usebackq delims=" %%c in (`curl -s -o nul -w "%%{http_code}" --noproxy 127.0.0.1 -X POST -H "Content-Type: application/json" -H "Accept: application/json, text/event-stream" "http://127.0.0.1:%~1/mcp" 2^>nul`) do (
        if not "%%c"=="000" exit /b 0
    )
    >nul ping -n 2 127.0.0.1
)
exit /b 1

:wait_http
REM %~1=端口  %~2=期望状态码
for /l %%i in (1,1,60) do (
    for /f "usebackq delims=" %%c in (`curl -s -o nul -w "%%{http_code}" --noproxy 127.0.0.1 "http://127.0.0.1:%~1/" 2^>nul`) do (
        if "%%c"=="%~2" exit /b 0
    )
    >nul ping -n 2 127.0.0.1
)
exit /b 1

:no_uv
echo [X] 虚拟环境需要重建，但没找到 uv。
echo     你的 uv 可能装了但不在双击运行时的 PATH 里。两个办法：
echo     1) 把 %%USERPROFILE%%\.local\bin 加进系统环境变量 Path，重新登录一次；
echo     2) 或直接删掉两个 .venv 目录前先别动，装了 uv 再重跑本脚本：
echo        powershell -c "irm https://astral.sh/uv/install.ps1 ^| iex"
goto :fail

:port_conflict
echo [X] 端口 %WEEKLY_PORT% 或 %APP_PORT% 被别的进程占着。
echo     若那正是本项目服务，直接访问 http://127.0.0.1:%APP_PORT% 即可。
echo     换端口： set WEEKLY_PORT=19080 ^&^& set APP_PORT=8901 ^&^& start.bat
echo     换了 WEEKLY_PORT 要同步改 novaagent\.env 里的 WEEKLY_MCP_URL。
goto :fail

:key_empty
echo [X] novaagent\.env 里 LLM_API_KEY / EMBEDDING_API_KEY 还是空的。
echo     对话模型 Key 在阿里云百炼申请，向量模型 Key 在硅基流动申请。
echo     正在用记事本打开 .env...
start notepad "%ROOT%\novaagent\.env"
goto :fail

:end
echo.
pause
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
