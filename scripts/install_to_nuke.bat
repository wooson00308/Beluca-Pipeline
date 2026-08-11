@echo off
chcp 65001 >nul
setlocal EnableExtensions

REM ============================================
REM BPE Nuke 연동 설치 (Windows)
REM ============================================
REM bpe.core.nuke_plugin_install 로 ~/.nuke/bpe 슬림 동기화

set "HERE=%~dp0"
set "REPO=%HERE%.."

if exist "%REPO%\src\bpe\__init__.py" (
  set "PYTHONPATH=%REPO%\src"
) else if exist "%HERE%bpe\__init__.py" (
  set "PYTHONPATH=%HERE%"
) else (
  echo [오류] bpe 패키지를 찾을 수 없습니다.
  pause
  exit /b 1
)

echo ============================================
echo BPE Nuke 연동 설치
echo ============================================

python -c "from bpe.core.nuke_plugin_install import ensure_nuke_plugin; r=ensure_nuke_plugin(force=True); print(r); raise SystemExit(0 if not r.get('error') else 1)"
if errorlevel 1 (
  echo [오류] Nuke 플러그인 설치에 실패했습니다.
  pause
  exit /b 1
)

echo.
echo [완료] %USERPROFILE%\.nuke\bpe
echo Nuke를 재시작하면 상단에 BPE 메뉴가 나타납니다.
pause
