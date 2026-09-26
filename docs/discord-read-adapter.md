# Discord Read Adapter

Phase 5, item 2 of [roadmap](roadmap.md). This adapter reads Discord through the MCP surface that
already exists in `eve-scene-runtime`. It does not create a second Discord client, a second cache,
or a Discord-owned project/task store.

## Source owner

| Field | Value |
|---|---|
| Source owner | `eve-scene-runtime` |
| Entrypoint | `src/discord/discord-mcp-server.mjs` (stdio JSON-RPC, line delimited) |
| Canonical state | Discord gateway, `allowed-channels.json` ACL, local SQLite/FTS5 message cache, forum threads |
| Consumed surface | 4 read tools, unchanged |
| Deliberately not consumed | 4 write tools of the same server |

Read tools wrapped by `DiscordReadAdapter`:

| Tool | Source requirement | Adapter limit |
|---|---|---|
| `discord_list_allowed_channels` | none | not budgeted |
| `discord_fetch_messages` | `retrieval_turn_id`, `channel_id` | `limit` 1..50, one of `before`/`after`/`around` |
| `discord_search_messages` | `retrieval_turn_id`, `query` | `limit` 1..10 |
| `discord_read_forum_thread` | `retrieval_turn_id`, `thread_id` | `limit` 1..50, one of `before`/`after`/`around` |

Write tools (`discord_create_sho_post`, `discord_edit_sho_post`, `discord_post_thread_message`,
`discord_edit_thread_message`) exist in the source. They are listed in
`DiscordReadAdapter.exposed_write_tools` for observability and are refused by the adapter. Mutating
Discord stays the job of the existing bot.

## Transport

`StdioMcpClient` in `src/all_tomorrow/adapters/mcp.py`:

- newline-delimited JSON-RPC over a subprocess (`initialize` → `notifications/initialized` → request)
- the server script is resolved against `script_roots` and must exist, so a pipeline step cannot
  execute an arbitrary script
- requests are serialized with a lock; responses are matched by JSON-RPC id, notifications ignored
- per-request timeout; on expiry the call fails and the client does not kill the source process
- `stderr` is discarded, so server-side secrets never reach a control-plane error
- 1 MiB line limit, because Discord message payloads can exceed the asyncio default

`McpClient` (HTTP JSON-RPC) is unchanged except for the new `call_tool_raw`, which returns the tool
result without collapsing `isError` so the adapter can read structured error codes.

## Guarantees

- **source owner**: every `DiscordReadResult` and every `DiscordReadError` names
  `eve-scene-runtime` and the `source_ref` (`edge:discord` by default).
- **read only**: the adapter refuses any tool outside the read surface, before any call is made.
- **timeout**: enforced by the transport; transport failures map to
  `DiscordErrorCode.TRANSPORT` and carry only the exception type, never the source message.
- **idempotency**: the read tools are side-effect free, so a retry is safe for Discord. A retry is
  *not* free for the source retrieval budget, so each call is counted per `retrieval_turn_id`
  before it is sent, mirroring `retrieval-budget.mjs` (`maxCalls` 4 per turn). The local mirror can
  be disabled with `max_calls_per_turn=None`.
- **trace propagation**: the source input schemas use `additionalProperties: false`, so a trace id
  cannot be injected as an extra argument. The trace travels as the retrieval turn id
  (`at:<trace_id>:<node_id>`, hashed when longer than the source limit of 128 characters) and is
  returned on the result.
- **fail closed**: `verify_contract()` fails when any read tool is missing, and a result without
  text content is a `CONTRACT_MISMATCH` instead of an empty success.

## Error mapping

| `structuredContent.code` at source | `DiscordErrorCode` |
|---|---|
| `DISCORD_ACCESS_DENIED` (ACL, guild mismatch) | `ACCESS_DENIED` |
| `RETRIEVAL_BUDGET_EXCEEDED` | `BUDGET_EXCEEDED` |
| anything else | `TOOL_ERROR` |
| transport/timeout | `TRANSPORT` |
| missing tool, non-object result, no text content | `CONTRACT_MISMATCH` |

The source text is truncated to 200 characters and the source `structuredContent` is preserved on
`DiscordReadError.details`. Argument contract violations raise `ContractError`/`ValueError` before
any network or process call.

## Not verified

The adapter was tested against a local fake stdio MCP server. It has not been run against the live
`eve-scene-runtime` process, so channel ACLs, the real retrieval budget, and message formatting are
unverified against production data.
