# ADR 0002: Discord Reads Go Through the Existing stdio MCP Surface

Status: Accepted

Date: 2026-09-18

## Context

`eve-scene-runtime`은 이미 Discord의 gateway, ACL, message cache, forum thread 접근을
`DiscordService` 한 곳에 모았고, 그 조회 능력의 일부를 `src/discord/discord-mcp-server.mjs`가
stdio JSON-RPC tool 8개로 노출한다. 그중 4개는 read-only이고 4개는 쓰기 작업이다.

Phase 5에서 중앙이 Discord를 읽어야 한다. 선택지는 (a) 중앙에 새 Discord client를 만든다,
(b) 기존 MCP surface를 소비한다, (c) `DiscordService` 코드를 중앙으로 복사한다.

추가 제약이 있다. read tool의 `inputSchema`는 `additionalProperties: false`이고 `retrieval_turn_id`가
필수다. 즉 임의의 trace field를 argument로 주입할 수 없다. 또한 `RetrievalBudget`은
`retrieval_turn_id`별로 tool-call 4회, payload 60 message / 15000자를 10분 동안 강제한다.

## Decision

Discord read는 기존 stdio MCP surface를 adapter로만 소비한다.

- `StdioMcpClient`은 line-delimited JSON-RPC transport일 뿐이며 tool/domain state를 소유하지 않는다.
  server script는 `script_roots` 안의 실제 파일이어야 한다.
- `DiscordReadAdapter`는 read 4개 tool만 호출한다. 같은 server의 write tool 4개는 알지만 호출하지
  않는다. 쓰기는 기존 bot의 책임으로 남긴다.
- trace propagation은 argument 주입이 아니라 `retrieval_turn_id`로 한다
  (`at:<trace_id>:<node_id>`, 128자를 넘으면 hash).
- source의 per-turn retrieval budget을 호출 전에 로컬에서 mirror한다. read는 Discord에는
  idempotent이지만 budget charge는 idempotent하지 않다.
- ACL/guild 오류, budget 초과, transport 실패, contract 불일치를 서로 다른 `DiscordErrorCode`로
  고정한다. Discord cache/message는 중앙 project/task 정본으로 승격시키지 않는다.

## Consequences

장점:

- 새 Discord client, 두 번째 cache, 두 번째 ACL이 생기지 않는다.
- 중앙 pipeline이 Discord 세부사항 대신 `DiscordReadResult`만 본다.
- source가 tool을 바꾸면 `verify_contract()`가 닫힌 상태로 실패한다.

비용:

- 중앙이 `eve-scene-runtime` process 기동(예: `node src/discord/discord-mcp-server.mjs`)에
  의존한다.
- turn id 길이 제한 때문에 trace 식별이 해시로 약간 lossy해진다.
- live 환경 검증이 아직 없다. fake stdio server로만 테스트했다.

## Revisit

- 중앙이 Discord에 쓰기를 해야 하는 요구가 생기면, 기존 bot 경로에 위임할지 별도 쓰기 adapter를
  만들지 ADR로 다시 결정한다.
- `eve-scene-runtime`이 HTTP MCP endpoint를 Discord read에 제공하면 transport만 교체한다.
