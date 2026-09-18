# ADR 0001: Separate Control Plane Repository

Status: Accepted

Date: 2026-09-18

## Context

현재 가장 많은 integration은 `eve-scene-runtime`에 모여 있다. 그 안에는 Eve runtime뿐 아니라 Discord bot, Manager bridge, MCP, Notion relay, scheduler도 있다. 새 Control Plane을 이 저장소 안에 구현하면 빠르게 재사용할 수 있지만 Eve domain이 중앙 orchestration의 구조적 owner처럼 된다.

## Decision

Control Plane은 `all-tomorrow`라는 별도 저장소에 둔다.

- All Tomorrow는 cross-system project/task/run/event/pipeline authority만 소유한다.
- Eve, Manager, Discord의 기존 canonical data는 이동하지 않는다.
- 기존 기능은 adapter로 호출한다.
- adapter contract가 확정되기 전에는 기존 저장소 코드를 복사하지 않는다.

## Consequences

장점:

- Eve를 교체하거나 중단해도 중앙 project history가 남는다.
- 중앙 pipeline이 특정 application/runtime에 종속되지 않는다.
- 기존 Notion/PostgreSQL ownership을 보존한다.

비용:

- 명시적인 adapter와 trace propagation이 필요하다.
- 초기에 repository가 하나 더 생긴다.
- 경계를 지키지 않으면 중앙 metadata와 domain state가 중복될 수 있다.

## Guardrail

새 필드를 저장하기 전 다음을 묻는다.

> 이 값은 cross-system orchestration의 정본인가, 아니면 기존 domain owner의 값을 복사하려는가?

후자라면 값 자체 대신 owner reference, version, provenance를 저장한다.

