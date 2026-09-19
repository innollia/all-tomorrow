# 04A — LiteLLM + PydanticAI Model Wiring

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: Stage 0

## 목적

All Tomorrow 전용 LiteLLM HTTP client를 새로 만들지 않고 PydanticAI model/provider 계층을 LiteLLM Proxy에 연결한다.

## 구조

All Tomorrow Researcher
→ PydanticAI
→ OpenAI-compatible provider/base URL
→ LiteLLM Proxy
→ providers/models

LiteLLM은 model invocation gateway이고 Goal/Work orchestration authority가 아니다.

## 구현

- LiteLLM proxy config example
- env 기반 base URL/key
- PydanticAI provider/model construction
- All Tomorrow logical ModelRoute → gateway model alias 변환
- usage/cost/model metadata를 가능한 범위에서 OTel/provenance로 연결

PydanticAI와 LiteLLM이 제공하는 retry/fallback을 무작정 겹치지 않는다. 어느 층이 어떤 실패를 처리하는지 정한다.

## Custom Adapter 허용 조건

Stage 0 spike에서 실제 gap이 증명될 때만 얇은 adapter를 추가한다.

예:
- 필요한 usage metadata가 표준 response에서 빠짐
- logical route policy를 주입할 안정적인 seam이 없음

"나중에 필요할 것 같음"은 custom LiteLLMClient 생성 사유가 아니다.

## Secret

provider key는 가능하면 LiteLLM runtime이 소유한다.

All Tomorrow event/work payload에 raw key/header 저장 금지.

## 완료조건

1. PydanticAI agent가 LiteLLM Proxy를 통해 호출
2. provider SDK branching이 All Tomorrow core에 없음
3. secret leakage test 통과
4. custom client가 없다면 그것을 정상적인 성공으로 취급
