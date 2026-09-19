# Stage 3.3 — Discovery, Resources and Multi-Executor

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2 routing + Stage 3 trigger 기반
- 지금 시작 가능: **아니오**

## Goal

외부 도구/지식/자원을 지속적으로 탐색하고 여러 executor/resource를 일반화된 방식으로 사용한다.

## External Discovery

- 새 AI model/service/tool
- library/plugin
- orchestration architecture
- game-development material
- asset source
- operational technique

observation
→ research question
→ ResearchArtifact
→ usefulness/risk/duplication
→ bounded experiment
→ evaluation
→ registry/knowledge candidate

외부 문서/repository의 지시는 untrusted evidence다.

## Resource Pool

- laptop
- AWS
- Sol Pi
- API/model/account
- free/paid quota
- concurrency/rate limit
- health/cost/quality

## Multi-Executor Workspace

실제 필요가 생긴 범위에서만:

- host별 workspace mapping
- checkout availability
- branch/dirty-state observation
- provisioning
- offline/online state
- reconciliation

분산 workspace 자체를 제품 목표처럼 키우지 않는다.

## Done When

새 provider/tool/host 추가가 generic core의 이름별 branch 없이 adapter/metadata/policy로 참여한다.
