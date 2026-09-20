# Roadmap Automation Contract

roadmap 상태와 문서 규칙을 사람이 수동으로만 맞추지 않는다.

## Machine-readable manifest

정본:
- docs/roadmap/manifest.json

각 packet entry:

- packet_id
- path
- parent_id
- stage
- status
- prerequisites[]
- evidence_blockers[]
- requirement_prefix
- required_evidence_levels[]
- implementation_paths[]
- test_paths[]

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

## CI

- tests/test_roadmap_lint.py
- .github/workflows/roadmap-lint.yml 또는 기존 docs/architecture lane

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
