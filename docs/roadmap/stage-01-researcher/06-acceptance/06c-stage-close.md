# 06C — Stage 1 Close Checklist

## Status

- 상태: **선행작업 대기**
- 선행조건: 06B 전체 통과
- 지금 시작 가능: **아니오**

## Stage close 전에 반드시 확인

### Tests

- `python -m pytest -q`
- live PostgreSQL integration
- acceptance suite
- worker adapter regression
- secret leakage tests

### Operations

- AWS restart/reboot recovery
- LiteLLM unavailable behavior
- laptop offline behavior
- laptop approval reauth
- daily report generation

### Documentation

AGENTS.md 규칙에 따라 같은 변경에서:

- 모든 하위 packet 상태 갱신
- 01/02/03/04/05 parent 상태 갱신
- Stage 1 index 갱신
- `docs/roadmap.md` Stage 1 → 개발완료
- Stage 2 → 시작안했음 / 지금 시작 가능=예
- Current Position 업데이트

### 금지

아래가 하나라도 사실이면 Stage 1 완료 처리하지 않는다.

- researcher가 restart에 state를 잃음
- autonomous Goal이 mock에만 존재
- self-improvement가 production에 실제 promotion되지 않음
- protected change를 AWS credential로 우회 가능
- daily report가 Event dump일 뿐 의미 복원 불가
- high-priority user Work가 background에 막힘
- user explicit choice가 inferred preference로 silently 대체됨
