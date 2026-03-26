---
name: deploy
description: BPE 새 버전 배포 절차. lint/test 확인, 태그 생성, GitHub Release 빌드까지 안내.
---

# 배포하기

코드 수정 후 새 버전을 배포하는 절차.

## 사전 조건

push 전 반드시 확인:
```bash
ruff check src/ tests/       # 린트 에러 0
ruff format src/ tests/      # 포맷 정리
python -m pytest tests/ -q   # 테스트 전부 통과
```

## 절차

### 1. 커밋 + push

```bash
git add -A
git commit -m "변경 내용 설명"
git push
```

### 2. CI 통과 확인

```bash
gh run list --limit 1
```
`completed success`가 나와야 함. 실패하면 로그 확인:
```bash
gh run view --log-failed
```

### 3. 버전 태그

현재 최신 태그 확인:
```bash
git tag --sort=-v:refname | head -5
```

새 태그 생성 + push:
```bash
git tag v0.x.x
git push origin v0.x.x
```

### 4. Release 빌드 확인 (3~5분)

```bash
gh run list --workflow=release.yml --limit 1
```

완료되면:
```bash
gh release view v0.x.x
```

### 5. 배포 완료

릴리즈 페이지에 `BPE-macOS.zip`, `BPE-Windows.zip`이 올라감.

## macOS 사용자 안내

다운받은 앱 실행 전:
```bash
xattr -cr ~/Downloads/BPE.app
```

## 릴리즈 실패 시

```bash
# 로그 확인
gh run view <run-id> --log-failed

# 태그 삭제 후 재시도
git tag -d v0.x.x
git push origin :refs/tags/v0.x.x

# 문제 수정 후 다시
git tag v0.x.x
git push origin v0.x.x
```
