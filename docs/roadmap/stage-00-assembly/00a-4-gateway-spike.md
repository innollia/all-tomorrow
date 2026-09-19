# 00A-4 — Tool Gateway Spike

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 00A-1

## 목적

durable backend 선택과 분리해 stable tool gateway를 선택한다.

첫 후보는 LiteLLM MCP Gateway지만 안정성을 전제하지 않는다.

## 중요한 현재 신호

2026-09-19 조사 시 LiteLLM은 MCP Gateway를 public feature로 노출하고 있지만 핵심 구현의 상당 부분이 repository의 `litellm/proxy/_experimental/mcp_server/` 경로에 있다.

따라서 "공식 feature"와 "우리 production seam으로 충분히 안정적"을 같은 뜻으로 취급하지 않는다.

## Candidate A — LiteLLM MCP Gateway

목표 구조:

PydanticAI Agent
→ stable MCPToolset id `all-tomorrow-tools`
→ LiteLLM fixed MCP endpoint
→ upstream MCP servers

검증:

- upstream 2개 이상 연결
- namespace collision
- list_tools/call_tool
- auth/credential ownership
- config reload/restart 요구
- 새 server/tool 추가 후 new run discovery
- in-flight durable run recovery와 tool discovery consistency
- gateway process restart
- model route 장애와 MCP route 장애가 같은 process에 있을 때 blast radius
- required MCP protocol/version compatibility
- allow/deny/filter
- OTel duplication
- prompt/tool payload logging

LiteLLM DB는 dynamic registry/virtual keys/budgets가 실제로 필요할 때만 추가한다.

초기 data policy:

- `store_prompts_in_spend_logs=false`
- `turn_off_message_logging=true`
- external logging callbacks off
- provider credential은 gateway runtime secret/env 소유

## Candidate B — FastMCP Fallback

LiteLLM이 아래 concrete requirement 중 하나를 못 닫을 때만 시험한다.

- required protocol/version compatibility
- dynamic provider/composition
- fine-grained transformation/filter
- process failure domain 분리 필요
- operationally stable tool registry가 LiteLLM보다 명확히 필요

FastMCP를 쓰더라도 background task/Docket durability는 활성화하지 않는다. durable owner는 하나만 둔다.

## Gateway Acceptance

- G01 fixed agent-side endpoint
- G02 upstream 2개 이상
- G03 namespace collision 없음
- G04 new-run discovery
- G05 in-flight recovery consistency
- G06 gateway restart recovery
- G07 credential non-leak
- G08 allow/deny/filter
- G09 no duplicate OTel span tree
- G10 no prohibited payload logging
- G11 exact-version pin 가능
- G12 upgrade contract를 regression test로 표현 가능

## 결정 규칙

LiteLLM이 G01~G12를 만족하면 model gateway와 MCP gateway 통합을 우선한다.

실패하면 durable backend를 탈락시키지 않는다. FastMCP fallback을 같은 G01~G12로 시험한다.

## 산출물

- selected gateway
- exact version
- reason for fallback if any
- separate process 필요 여부
- config reload semantics
- auth/secret ownership
- tool discovery/versioning contract
- known experimental/upgrade risk
