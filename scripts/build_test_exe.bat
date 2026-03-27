@echo off
REM Beluca-Pipeline — 로컬 테스트 exe 빌드 (상세는 build_test_exe.ps1)
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_test_exe.ps1" %*
