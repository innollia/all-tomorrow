# 04A — LiteLLM Gateway

## Status

- 상태: **시작안했음**
- 지금 시작 가능: **예**
- 선행조건: 없음
- 완료 후 열림: 04D AWS Runtime 일부

## 목적

All Tomorrow 안에 provider별 SDK 분기를 늘리지 않고 LiteLLM Proxy를 중앙 model gateway로 사용한다.

All Tomorrow는 Goal/Work orchestration authority를 유지하고 LiteLLM은 model invocation/routing/telemetry 계층으로만 둔다.

## 구현 형태

LiteLLM Python SDK를 application core에 직접 박지 않는다.

초기 구조:

All Tomorrow
→ HTTP/OpenAI-compatible adapter
→ LiteLLM Proxy
→ providers/models

이렇게 두면 LiteLLM 자체를 교체해도 Goal/Work layer를 건드리지 않는다.

## 수정 파일

- 새 파일: `src/all_tomorrow/adapters/llm.py`
- 수정: `src/all_tomorrow/adapters/__init__.py`
- 수정: `src/all_tomorrow/models.py`
- 수정: `.env.example`
- 새 파일: `deploy/litellm/config.example.yaml`
- 새 테스트: `tests/test_llm_adapter.py`

기존 dependency인 `httpx` 재사용. All Tomorrow app에 `litellm` Python package를 추가하지 않는다.

## Adapter contract

`LiteLLMClient`:

constructor:

- base_url
- api_key_ref 또는 secret resolver가 넘긴 runtime key
- timeout_seconds
- httpx AsyncClient injection 가능

public method 최소:

- `responses(model, input, *, metadata=None, max_output_tokens=None)`
- `chat_completion(model, messages, *, metadata=None)`

초기 researcher path는 하나만 실제 사용해도 되지만 adapter contract는 LiteLLM이 제공하는 OpenAI-compatible Responses/Chat endpoint를 분리해 둔다.

## Secret rule

DB/Event에는 API key 값 저장 금지.

`.env.example`에는 이름만:

- `LITELLM_BASE_URL`
- `LITELLM_API_KEY`

실제 key는 runtime secret/environment에서 공급.

request/response Event에는 key/header/raw prompt를 넣지 않는다.

## ModelRoute 정리

현재 `models.py`의 `ModelRoute` / `ModelRouter`는 metadata-level route로 유지.

추가 metadata 후보:

- gateway_alias
- model
- capabilities
- status
- fallback_aliases

provider credential을 `ModelRoute`가 직접 꺼내 쓰게 확장하지 않는다.

LiteLLM 뒤 provider 선택과 All Tomorrow의 Work-level resource 선택을 같은 개념으로 합치지 않는다.

## Telemetry

adapter 반환 metadata에서 가능한 범위:

- selected model
- provider/model deployment identifier
- latency
- usage token counts
- reported cost

를 normalization.

값이 없으면 unknown으로 둔다. 추정값을 사실처럼 저장하지 않는다.

## LiteLLM config example

`deploy/litellm/config.example.yaml`:

- 최소 model_list 예시
- secret은 `os.environ/...` 참조
- master key도 env 참조
- 실제 개인 provider/account 이름/키를 commit하지 않음

## 테스트

httpx mock transport로:

- responses success
- chat completion success
- timeout/network error normalization
- non-2xx sanitization
- key가 exception/Event representation에 노출되지 않음
- usage/cost metadata optional 처리

실제 provider 호출은 unit test에서 하지 않는다.

## 하지 말 것

- provider별 if/else를 researcher에 추가
- LiteLLM DB를 All Tomorrow canonical state로 사용
- raw provider key DB 저장
- 첫 packet에서 모든 fallback/budget feature 구현
- model selection policy를 LiteLLM에 완전히 양도

## 완료조건

1. All Tomorrow가 한 adapter로 LiteLLM Proxy 호출 가능
2. secret leakage test 통과
3. provider/model metadata normalization 가능
4. app core에 provider SDK 의존성 추가 없음
