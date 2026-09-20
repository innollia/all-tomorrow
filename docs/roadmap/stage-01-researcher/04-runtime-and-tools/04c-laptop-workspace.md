# 04C — Laptop Workspace Resolver

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0 완료

## 목적

logical project/source identity와 host-local checkout path를 분리하고 worker가 허용된 workspace 밖으로 빠져나가지 못하게 한다.

## Mapping

catalog에는 logical source만 저장.
local ignored file은 executor_id + project_id → path binding을 저장한다.

WorkspaceBinding:

- executor_id
- project_id
- path
- allowed_root
- optional expected source/ref

## Resolution invariants

1. path와 allowed_root 모두 realpath로 normalize
2. workspace realpath가 allowed_root 하위여야 함
3. worker allowed_roots에도 같은 normalized root가 포함되어야 함
4. symlink/junction을 따라 root 밖으로 나가면 reject
5. missing/non-directory는 explicit unavailable
6. expected repo source가 있으면 remote/repo identity mismatch를 관측해 reject/warn policy 적용

## Dirty tree policy

1차에서 자동 stash/reset/checkout하지 않는다.

repo mutation Work 전에:

- dirty/untracked state 관측
- current branch/HEAD ref 기록
- proposal/Work가 요구한 baseline과 다르면 NEED_USER 또는 explicit safe disposable worktree path
- 사용자 기존 변경을 조용히 덮어쓰지 않음

03C sandbox는 disposable worktree를 별도 생성할 수 있으나 canonical laptop checkout을 암묵 수정하지 않는다.

## Requirements

- 정상 resolve
- unknown project/executor
- duplicate binding
- nonexistent path
- symlink/junction escape
- resolver root와 worker allowed_root mismatch
- logical source mismatch
- dirty tree detection
- catalog에 host-local path 없음

## 완료조건

logical project identity와 local cwd가 분리되고 resolver와 worker가 같은 filesystem boundary를 이중 검증해야 한다.
