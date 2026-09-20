# 04F — Artifact Store & Integrity

## Status
- 상태: 선행작업 대기
- 선행조건: Stage 0 + 01 domain/schema
- 지금 시작 가능: 아니오

## 목적
ArtifactRef의 bytes 저장소, atomic finalize, integrity, authorization, retention/GC를 구현할 계획을 확정한다.

## 예정 구현 위치
- `src/all_tomorrow/artifacts.py`
- `src/all_tomorrow/storage/artifact_store.py`
- `migrations/00xx_artifacts.sql`
- `tests/test_artifacts.py`
- `tests/integration/test_artifact_integrity.py`

기존 동등 module이 있으면 00E에서 경로를 교체.

## Backend selection
00E/04D에서 personal AWS topology에 맞는 1차 bytes backend를 하나 확정:
- local persistent filesystem
- S3/object storage
- 기타 이미 검증된 object store

선택 기준:
atomic finalize, content-hash addressing, backup, access control, operational complexity.

## Lifecycle
temporary upload → hash → immutable finalize → metadata/ref transaction.
attach 실패 object는 orphan GC candidate.
metadata는 있는데 bytes/hash가 없으면 integrity failure + REPAIR_REQUIRED.

## Requirements
- S1-04F-01 immutable content hash
- S1-04F-02 user/project access enforcement
- S1-04F-03 temporary/orphan GC
- S1-04F-04 backup/retention/purge
- S1-04F-05 approval/evaluation artifact substitution 방지
- S1-04F-06 oversized raw data durable journal/Event 복제 금지
