# 04C — Laptop Workspace Resolver

## Status

- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 없음

## 목적

1차 repo mutation을 사용자의 노트북 하나에 한정하면서 project identity와 `C:\...` 같은 host-local path를 분리한다.

## 수정 파일

- 새 파일: `src/all_tomorrow/workspaces.py`
- 수정: `projects/catalog.yaml`
- 새 파일: `projects/workspaces.example.yaml`
- 수정: `.gitignore`
- 새 테스트: `tests/test_workspaces.py`
- 필요 시 보강: `tests/test_projects.py`

## Project catalog

`projects/catalog.yaml`의 source_refs에서 host-local repo path를 logical source로 바꾼다.

예:

- All Tomorrow: `github:innollia/all-tomorrow`
- Eve: 실제 GitHub repository identity
- domain refs는 그대로 유지

실제 local checkout path는 catalog 정본에 넣지 않는다.

## Local mapping

commit되는 template:

`projects/workspaces.example.yaml`

실제 사용자 파일:

`projects/workspaces.local.yaml`

.gitignore에 local file 추가.

형태:

executor_id
→ project_id
→ path

초기 executor_id는 하나:

- `laptop`

## workspaces.py

dataclass:

`WorkspaceBinding`

- executor_id
- project_id
- path

`WorkspaceResolver`:

- config load
- duplicate binding reject
- `resolve(project_id, executor_id) -> Path | None`
- path resolve
- 존재하는 directory인지 확인
- symlink/path traversal 결과가 configured root 밖으로 빠지지 않는지 확인

1차에서는 checkout 생성/clone/pull을 자동으로 하지 않는다.

binding 없으면 상위 orchestration이 WAITING/NEED_USER/provisioning을 결정하도록 명시적 missing result를 반환한다.

## Worker 연결

worker에 project_id만 던져 resolver가 내부에서 cwd를 암묵적으로 찾게 하지 않는다.

상위 execution resolution이:

project_id + executor_id
→ WorkspaceResolver
→ cwd
→ WorkerRequest.payload["cwd"]

순서로 명시적으로 조립한다.

기존 worker의 cwd safety check는 그대로 유지해 2중 경계를 둔다.

## 테스트

- all-tomorrow/laptop 정상 resolve
- unknown project → None/error contract
- unknown executor
- duplicate binding reject
- nonexistent path
- path normalization
- worker allowed_root 밖 mapping 차단
- catalog에 `repo:C:/...` 잔존하지 않는지 검사

## 하지 말 것

- Git clone/pull 자동화
- dirty tree 자동 stash
- branch reconciliation
- AWS/Sol Pi mapping 실제 구현
- network filesystem
- path를 Project.project_id로 사용

## 완료조건

logical project source와 laptop cwd가 분리되고, 기존 worker는 resolver가 준 cwd로 그대로 실행 가능.
