# Stage 3.5 — Acceptance

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 3.1~3.4 완료
- 지금 시작 가능: **아니오**

## Required scenarios

1. Proactive brief: owner refs/freshness와 함께 실제 전달
2. School material: original Artifact→extraction→owner/ref→Work→result
3. Owner conflict: stale central summary가 canonical owner를 overwrite하지 않음
4. Trigger: duplicate/restart/DST/misfire 안전
5. Webhook: auth/replay attack 실패
6. Knowledge: lesson candidate→accept→reuse→outcome→confidence update
7. Conflicting/stale lesson 처리
8. New service/library discovery→untrusted sandbox→bounded experiment
9. Supply-chain credential/sandbox attack 실패
10. Resource concurrent reservation/unknown quota
11. Multi-executor offline/dirty workspace reconciliation
12. Long-horizon Goal→dynamic graph→milestones→playable/runnable demo
13. Resource failure 중 same Goal continuation
14. User feedback bound to exact artifact→follow-up Work
15. Broad-evidence self-improvement still frozen-eval/protected rail
16. 통합 loop: external change→autonomous Goal→artifact/system improvement→report/brief→user feedback

## Failure conditions

- personal/project state가 별도 island로 남음
- user manual handover가 매 단계 필요
- provider/host 이름별 core branch
- trigger/background state restart loss
- duplicate trigger가 duplicate mutation
- lesson reuse outcome 없이 "학습됨" 주장
- activity를 long-horizon progress로 주장
- external discovery가 production credentials로 실행
- inferred preference가 explicit choice 변경
- protected boundary AWS가 약화
- 사용자가 시스템 행동/출처/결과를 복원 불가

## Evidence

- owner/trigger/knowledge/resource DB: L1
- restart/resource failure: L2
- proactive delivery/multi-executor/long-horizon actual environment/security: L3

## Stage complete only if

시나리오가 같은 Request/Goal/Work/Run/Trigger/Artifact/owner provenance를 공유하는 하나의 시스템에서 통과하고 required L2/L3 evidence가 실제 실행되어야 한다.
