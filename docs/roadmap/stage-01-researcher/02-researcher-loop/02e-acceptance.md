# 02E — Researcher Loop Acceptance

## Status

- 상태: **선행작업 대기**
- 선행조건: 02A~02D 완료
- 지금 시작 가능: **아니오**

## 테스트 파일

- 새 파일: `tests/integration/test_researcher_loop.py`

## 필수 시나리오

1. 정상 상태 → wake → NOOP → 새 Goal/Work 없음
2. unlabeled repeated failure Event → wake → investigation Work 생성
3. open Work 정체 + evidence → 새 진단 Work 또는 Goal
4. 자기 이전 `researcher.decision`과 결과가 다음 snapshot에 포함
5. 사용자 요청 없이 autonomous Goal 생성
6. 같은 observation을 재처리해도 duplicate Work 없음
7. budget exhaustion 뒤 Work storm 없음
8. malformed LLM output이 state mutation하지 않음
9. researcher restart 뒤 cursor/lineage 유지

## 완료 시 index 변경

- 02A~02E → 개발완료
- `02-researcher-loop.md` → 개발완료
- Stage 1 index의 Researcher Loop → 개발완료
- Stage 1.3 Evaluation → 시작안했음 / 지금 시작 가능=예
- Stage 1.5 Report & Priority도 선행조건 충족 여부 재계산
