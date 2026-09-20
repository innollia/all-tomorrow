# Stage 2.5 — Acceptance

## Status

- 상태: **선행작업 대기**
- 선행조건: Stage 2.1~2.4 완료
- 지금 시작 가능: **아니오**

## Required scenarios

1. Any-device: remote authenticated Request→result
2. Duplicate ingress: two deliveries→one logical Request/mutation
3. Restart-safe NEED_USER: device A request, restart, device B answer
4. Multi-client continuity: Web/Discord/API가 same Goal/Work state 조회
5. Handover gap: 새 worker가 bounded ContextPack으로 continuation
6. Cancel during external mutation: unknown effect reconciliation
7. Worker/provider failure: filter/fallback/new Run provenance
8. Cross-system action: one ingress→different project owner mutation
9. Artifact continuity: result hash/ref를 다른 client에서 retrieval
10. Backup restore: restored runtime에서 canonical Request/Goal/Work continuity
11. User priority: hard commitment가 background researcher보다 우선
12. Security: cross-user access/CSRF/session replay 실패

## Evidence levels

- adapter/policy: L0
- DB/dedup/routing/context: L1
- process restart/cancel ambiguity: L2
- remote HTTPS/AWS/backup/security: L3

## Stage complete only if

위 scenario가 개별 demo가 아니라 같은 Request→Goal→Work→Run→Artifact provenance를 공유하고 필수 L2/L3 evidence가 not-run 상태가 아니어야 한다.
