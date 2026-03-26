---
name: deploy
description: Documents BPE release workflow — ruff, pytest, VERSION.txt bump, CI success, v* tag push, GitHub Actions Release zips. Use when shipping a version, cutting a release, or publishing BPE binaries.
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

### 1. 현재 최신 태그 확인 + 다음 버전 결정

```bash
git tag --sort=-v:refname | head -5
```

최신 태그를 확인한 뒤, 다음 버전을 계산한다:
- 버그 수정/패치: 마지막 자리 +1 (예: 0.2.1 → 0.2.2)
- 기능 추가: 가운데 자리 +1, 마지막 자리 0 (예: 0.2.2 → 0.3.0)
- 대규모 변경: 첫째 자리 +1 (예: 0.3.0 → 1.0.0)

사용자에게 반드시 질문할 것:
- 현재 최신 태그가 무엇인지 알려주기
- 이번 변경이 패치/기능/대규모 중 어느 쪽인지 확인하기
- 계산한 다음 버전을 제시하고, 이 버전으로 진행할지 확인받기

확인 없이 버전을 올리거나 태그를 생성하지 말 것.

### 2. VERSION.txt 수정

사용자가 확인한 버전으로 수정:
```bash
echo "<확정된 버전>" > VERSION.txt
git add VERSION.txt
git commit -m "chore: v<확정된 버전> 버전 범프"
```

### 3. push

```bash
git push
```

### 4. CI 통과 확인

```bash
gh run list --limit 1
```
`completed success`가 나와야 함. 실패하면 로그 확인:
```bash
gh run view --log-failed
```

### 5. 버전 태그

새 태그 생성 + push:
```bash
git tag v0.x.x
git push origin v0.x.x
```

### 6. Release 빌드 확인 (3~5분)

```bash
gh run list --workflow=release.yml --limit 1
```

완료되면:
```bash
gh release view v0.x.x
```

### 7. 배포 완료

릴리즈 페이지에 `BPE-macOS.zip`, `BPE-Windows.zip`이 올라감.
URL: `https://github.com/wooson00308/Beluca-Pipeline/releases/tag/v0.x.x`

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
