# 05B — Daily Report Composer

## Status

- 상태: **선행작업 대기**
- 선행조건: 05A + 04A LiteLLM
- 지금 시작 가능: **아니오**

## 목적

사용자가 "오늘 시스템이 뭘 원해서 뭘 했고 뭐가 달라졌는지" 빠르게 복원할 수 있는 보고서를 만든다.

## 수정 파일

- 수정: `src/all_tomorrow/reports.py`
- 새 테스트: `tests/test_report_composer.py`

## 고정 section

최소:

1. Autonomous Goals
2. Work Progress
3. Research Findings
4. System Changes
5. Rollbacks / Rejections
6. Resource & Cost
7. Approval Pending
8. Needs User

section은 output contract이고 problem taxonomy가 아니다.

## 생성 방식

1. 05A projection에서 structured facts 생성
2. deterministic skeleton 생성
3. LLM은 요약/우선순위 표현만 수행
4. source ref 없는 새로운 사실 추가 금지
5. LLM 실패 시 structured fallback report 생성

보고서는 LLM 성공에 의존해 유실되면 안 됨.

## 비용

보고서 자체도 budget 계정에 포함.

이미 요약된 내용이 없으면 source Event를 무제한 prompt에 넣지 않는다.

## 테스트

- source fact만 사용
- LLM unavailable fallback
- pending protected proposal 구분
- autonomous/user Goal 구분
- cost unknown을 0으로 표시하지 않음

## 완료조건

LLM이 죽어도 생성 가능한, source-backed 일일보고서.
