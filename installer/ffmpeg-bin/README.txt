Windows PyInstaller 빌드에 포함할 ffmpeg.exe / ffprobe.exe 를 두는 폴더입니다.

- 로컬·CI 빌드 전에 저장소 루트에서:
  PowerShell:  .\scripts\fetch_ffmpeg_windows.ps1
- 위 스크립트가 gyan.dev 배포 ZIP에서 bin만 추출해 이 폴더에 복사합니다.
- *.exe 는 git에 올리지 않습니다(.gitignore).

FFmpeg는 LGPL/GPL 라이선스입니다. 배포 시 고지 요건을 따르세요.
