# 02B — Researcher Wake and Decision

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 02A + 04A LiteLLM Gateway
- 완료 후 열림: 02C Decision Materialization

## 목적

trigger opportunity를 받아 observation snapshot을 모델에 전달하고, no-op 또는 구조화된 decision을 얻는 generic researcher entry point를 만든다.

## 수정 파일

- 수정: `src/all_tomorrow/researcher.py`
- 수정: `src/all_tomorrow/adapters/llm.py`
- 새 파일: `src/all_tomorrow/researcher_prompt.py`
- 새 테스트: `tests/test_researcher.py`

## ResearcherService

constructor dependency:

- WorkStateStore/PostgresStore
- ObservationBuilder
- LiteLLMClient
- model alias/config
- budget policy

public method:

- `wake(origin, *, user_id, project_id=None, metadata=None)`

## wake 순서

1. `researcher.woke` Event
2. ObservationSnapshot 생성
3. cheap preflight:
   - 처리할 새 observation 없음
   - budget 없음
   - disabled
   이면 모델 호출 없이 noop
4. model invocation
5. structured decision parse/validate
6. decision Event 저장
7. materialization은 02C에 위임
8. 성공적으로 durable 기록된 뒤 cursor advance

## Structured Decision

모델 출력은 자유문장 하나로 끝내지 않는다.

최소 schema:

- `summary`
- `action`: NOOP | CREATE_GOAL | CREATE_WORK | REVISE_WORK | ASK_USER | PROPOSE_IMPROVEMENT
- `reason`
- `evidence_refs[]`
- `target_goal_id optional`
- `target_work_id optional`
- `proposed payload`
- `confidence optional`

여기서 action 목록은 **문제 종류 taxonomy가 아니라 control-plane mutation primitive**다.

## Prompt 원칙

prompt는 다음을 요구:

- evidence ref 없는 강한 claim 금지
- 할 가치가 없으면 NOOP 허용
- 새 Goal 생성 허용
- 자기 자신의 policy/prompt/code도 개선 대상 가능
- 사용자 명시적 선택을 몰래 바꾸지 않음
- 필수 정보 없으면 ASK_USER
- raw secret 추측 금지

prompt 자체는 version/ref를 남겨 이후 self-improvement 대상이 되게 한다.

## Parse 실패

- malformed response를 임의 보정해 mutation하지 않음
- researcher.invalid_decision Event
- bounded retry 1회까지 허용 가능
- 계속 실패하면 wake 종료

## 테스트

- observation 없음 → LLM 호출 0회 + NOOP
- valid NOOP
- CREATE_GOAL decision parse
- CREATE_WORK decision parse
- malformed response → mutation 없음
- evidence_refs unknown → reject
- prompt version/ref Event 기록

## 하지 말 것

- wake마다 무조건 새 Work 생성
- model이 직접 DB write
- provider별 researcher branch
- 특정 실패 이름에 대한 if/else
- 별도 meta-meta researcher

## 완료조건

generic wake가 current observation을 보고 mutation primitive 또는 NOOP를 안전하게 반환.
