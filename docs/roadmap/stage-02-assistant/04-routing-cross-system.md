# Stage 2.4 — Routing and Cross-System Action

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.3
- 지금 시작 가능: **아니오**

## 목적

worker/model/tool/executor를 capability/authority/health/cost evidence로 선택하고 failure 시 provenance를 유지한 fallback/replan을 수행한다.

## Resource candidate metadata

- resource_id
- kind: worker/model/tool/executor
- capabilities
- project/source reachability
- authority/permission scope
- health/freshness
- availability/concurrency
- cost/quota observations
- quality/evaluation refs
- latency observations
- version
- failure history refs

provider/worker 이름은 metadata일 수 있으나 core selection branch의 조건으로 사용하지 않는다.

## Selection pipeline

1. hard filter
   - required capability
   - owner/source/project access
   - authority/risk
   - online/healthy enough
   - budget/quota
2. rank remaining
   - user/project preference policy
   - quality evidence
   - expected cost/latency
   - locality/data boundary
3. selection provenance 저장
4. Run 시작
5. failure classification
6. same Run recovery 또는 new Run fallback/replan 결정

ranking formula/policy는 versioned config/ref를 가진다. registry의 insertion order/sort가 implicit policy가 되지 않는다.

## Fallback

- retryable transport failure: 00B owner policy
- resource unavailable before side effect: alternate candidate로 새 Run 가능
- external effect ambiguity: 다른 resource로 blind replay 금지
- no qualified candidate: NEED_USER/WAITING/explicit failure
- budget exhausted: cheaper fallback을 자동 선택할 수 있는 범위를 policy로 명시; explicit user model/resource requirement를 몰래 바꾸지 않음

## Cross-system mutation

target owner adapter가 mutation authority를 검증한다.

예:
Web/Manager Request
→ project:eve
→ repository Work
→ authorized workspace/worker
→ commit/artifact
→ validation
→ source-owner update
→ central provenance/result ref

central DB가 target project's canonical source를 몰래 복제/overwrite하지 않는다.

## Requirements

- candidate hard-filter violation 선택 0
- insertion order 변화가 selection 결과를 policy 없이 바꾸지 않음
- failed resource → evidence-backed fallback/new Run
- ambiguous mutation → blind fallback 없음
- explicit user resource choice가 inferred preference로 대체되지 않음
- cross-project mutation이 owner adapter/authority 통과
- 새 provider/worker 추가에 core name branch 없음

## 완료조건

실제 LiteLLM + worker 2종 이상 + cross-project mutation에서 selection/fallback provenance가 남고 failure에도 Goal이 유지되어야 한다.
