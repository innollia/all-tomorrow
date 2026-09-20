# Roadmap Automation Contract

## Status

- 상태: **계획만 작성됨**
- 실제 linter/test/GitHub Actions 구현: **아직 하지 않음**
- 이번 roadmap 구체화 작업의 범위는 이 문서와 manifest 설계까지

roadmap 상태와 문서 규칙을 장기적으로 사람이 수동으로만 맞추지 않기 위한 구현 계획이다.


## Machine-readable manifest

정본:
- docs/roadmap/manifest.json

각 packet entry의 core fields:

- packet_id
- path
- parent_id
- stage
- status
- prerequisites[]
- requirement_prefix
- required_evidence_levels[]

implementation-ready packet에서 추가로 필수:

- evidence_blockers[]
- implementation_paths[]
- test_paths[]
- review_required

현재 manifest는 dependency/status 정본을 먼저 만든 상태이며, 추가 fields는 해당 packet이 시작 가능 상태로 열리기 전에 채운다.

status enum:
- 개발중
- 개발완료
- 시작안했음
- 선행작업 대기

## Linter

planned/required script:
- scripts/roadmap_lint.py

checks:

1. manifest path exists
2. parent/child status consistency
3. prerequisites exist and no dependency cycle
4. 개발완료 packet prerequisites all 개발완료
5. 시작 가능 상태 계산과 markdown status 일치
6. packet requirement IDs unique and prefix compliant
7. required sections 존재
8. stale old filenames/forbidden phrases detection
9. implementation/test paths declared when packet is implementation-ready
10. upstream contract revision change가 downstream review marker 없이 넘어가지 않음

## Requirement ID convention

전역:
- S{stage}-{packet}-{NN}

예:
- S0-00B1-01
- S1-01A-01
- S2-21A-01
- S3-32C-01

legacy IDs는 rewrite 시 migration table을 남기고 신규 ID로 정규화한다.

manifest migration fields:
- requirement_prefix: 현재 문서에서 실제 사용하는 prefix
- target_requirement_prefix: 목표 전역 prefix
- prefix_migration_pending: 둘이 다를 때 true

Stage 1 legacy packet은 구현 직전 rewrite에서 requirement id를 바꾸고, old→new ID mapping을 해당 packet 또는 audit에 남긴다.

## CI — 향후 구현 계획

예정 위치:
- tests/test_roadmap_lint.py
- .github/workflows/roadmap-lint.yml 또는 기존 docs/architecture lane

현재는 위 파일을 생성하지 않는다.

PR hard gate:
- roadmap/AGENTS 변경 시 linter 필수
- manifest와 markdown 상태 불일치 실패
- broken roadmap links 실패

## Upstream invalidation

manifest는 contract dependency도 가진다.

- identity
- failure/recovery
- security/artifact
- control-plane
- delivery/consistency
- operations/security

contract version이 바뀌면 affected packet에 review_required=true가 자동/수동으로 설정되고 해제 전 개발완료 유지 금지.
