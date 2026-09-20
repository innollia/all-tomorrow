# Stage 0 Implementation Map

이 문서는 Stage 0 packet의 **예정 구현 위치**를 고정한다. 실제 코드는 이 계획 작업에서 수정하지 않는다.

| Packet | 예정 구현/설정 | 예정 테스트/증거 |
|---|---|---|
| 00A-1 | `tests/stage0/harness/`, `tests/stage0/fixtures/` 또는 기존 test layout에 동등 구조 | D01~D12 common harness |
| 00A-2 | `src/all_tomorrow/adapters/durable/dbos.py` 후보 | `tests/stage0/test_dbos_spike.py` |
| 00A-3 | `src/all_tomorrow/adapters/durable/restate.py` 후보 | `tests/stage0/test_restate_spike.py` |
| 00A-4 | `src/all_tomorrow/adapters/mcp_gateway.py`, gateway config 후보 | `tests/stage0/test_gateway_spike.py` |
| 00A-5 | production dependency/config pin + ADR | compatibility/replay/privacy evidence |
| 00B-1 | `src/all_tomorrow/domain/{ids,state,outcomes,events,sources}.py` 후보 | domain contract tests |
| 00B-2 | `src/all_tomorrow/ports/{durable,agent,tools,workers}.py`, `errors.py` | adapter/error contract tests |
| 00B-3 | `src/all_tomorrow/delivery.py`, delivery store, migration | reconciliation integration |
| 00B-4 | `src/all_tomorrow/execution_policy.py`, policy config | retry ceiling tests |
| 00B-5 | tool registry + authorization policy | allow/confirm/deny fixtures |
| 00B-6 | 없음: contract acceptance packet | contract/architecture scan |
| 00C | `tests/stage0/failure/`, process barrier/fixture helpers | C-01~C-10 L1/L2 evidence |
| 00D | OTel/eval/CI **구현 계획 대상**; exact file names는 00C repo shape 확인 후 확정 | D-series trace/eval/CI evidence |
| 00E | ADR/architecture/roadmap rewrite only | Stage 1 consistency audit |

## 규칙

- 경로는 Stage 0에서 실제 repo 구조를 읽은 뒤 기존 module이 있으면 그곳에 합친다.
- 이 map의 목적은 새 framework/directory를 강제로 만드는 것이 아니라 책임 위치를 미리 지정하는 것.
- 기존 동등 module이 있으면 새 파일 생성보다 그 module 확장을 우선하며 00E에 최종 경로를 기록.
