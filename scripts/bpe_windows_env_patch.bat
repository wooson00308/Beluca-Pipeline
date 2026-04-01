@echo off
REM BPE와 별도로 실행 — 사용자 환경 변수(BPE_NUKEX_EXE, BPE_SERVER_ROOT) 설정
REM 이 배치 파일과 bpe_windows_env_patch.ps1 을 같은 폴더에 두고 더블클릭하세요.

chcp 65001 >nul
title BPE 환경 패치
cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bpe_windows_env_patch.ps1"
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  echo.
  echo 종료 코드: %ERR%
)
echo.
pause
