@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================
REM BPE Nuke 연동 설치 (Windows)
REM ============================================
REM 이 스크립트는 bpe 패키지를 .nuke/ 폴더에 복사하고
REM menu.py에 hook을 추가합니다.

set "HERE=%~dp0"

REM bpe 패키지 소스 탐색
if exist "%HERE%..\src\bpe\__init__.py" (
  set "BPE_SRC=%HERE%..\src\bpe"
) else if exist "%HERE%bpe\__init__.py" (
  set "BPE_SRC=%HERE%bpe"
) else (
  echo [오류] bpe 패키지를 찾을 수 없습니다.
  echo 프로젝트 루트의 scripts 폴더에서 실행하거나,
  echo 배포 폴더에 bpe 디렉터리가 있는지 확인하세요.
  pause
  exit /b 1
)

set "NUKE_DIR=%USERPROFILE%\.nuke"

echo ============================================
echo BPE Nuke 연동 설치
echo ============================================

if not exist "%NUKE_DIR%" (
  mkdir "%NUKE_DIR%"
)

REM bpe 패키지 전체를 .nuke 아래에 복사
echo [1/2] bpe 패키지를 %NUKE_DIR%\bpe 로 복사합니다...
if exist "%NUKE_DIR%\bpe" (
  rmdir /S /Q "%NUKE_DIR%\bpe"
)
xcopy /E /I /Q /Y "%BPE_SRC%" "%NUKE_DIR%\bpe" >nul
if errorlevel 1 (
  echo [오류] bpe 패키지 복사에 실패했습니다.
  pause
  exit /b 1
)

REM menu.py에 BPE hook 추가 (이미 있으면 건너뜀)
echo [2/2] menu.py에 BPE hook을 추가합니다...
set "MENU_PY=%NUKE_DIR%\menu.py"
set "HOOK_MARKER=# BPE_HOOK_START"

if exist "%MENU_PY%" (
  findstr /C:"%HOOK_MARKER%" "%MENU_PY%" >nul 2>&1
  if not errorlevel 1 (
    echo       menu.py에 이미 BPE hook이 있습니다. 건너뜁니다.
    goto :done
  )
)

REM hook 추가
(
  echo.
  echo %HOOK_MARKER%
  echo try:
  echo     from bpe.nuke_plugin.menu_setup import add_setup_pro_menu
  echo     add_setup_pro_menu^(^)
  echo     from bpe.nuke_plugin.tool_hooks import reload_tool_hooks
  echo     reload_tool_hooks^(^)
  echo except Exception as _bpe_err:
  echo     import nuke
  echo     nuke.tprint^("[BPE] menu.py hook 로드 실패: " + str^(_bpe_err^)^)
  echo # BPE_HOOK_END
) >> "%MENU_PY%"

:done
echo.
echo [완료] 설치 경로:
echo   %NUKE_DIR%\bpe
echo   %MENU_PY%
echo.
echo Nuke를 재시작하면 상단에 setup_pro 메뉴가 나타납니다.
pause
