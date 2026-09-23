# 2.1C — Discord / CLI Ingress

## 선행
2.1A

## 구현 위치
- 새/수정: src/all_tomorrow/adapters/discord.py
- 새/수정: src/all_tomorrow/cli.py
- tests: tests/test_discord_ingress.py
- tests: tests/test_cli_ingress.py

## 핵심
Discord message/event identity를 Delivery key로 사용.
CLI mutation은 idempotency key를 생성/표시하고 retry 시 재사용 가능.
local conversation과 central escalation 분리.

## Requirements
- S2-21C-01 duplicate Discord event→mutation 1개
- S2-21C-02 local-only message→central Work 0
- S2-21C-03 durable/cross-project request→central escalation provenance
- S2-21C-04 CLI retry identity 보존
