# 01E — Live PostgreSQL Verification

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01A + 01B + 01C + 01D 완료
- 완료 후 열림: Stage 1.2 Researcher Loop

## 목적

mock SQL test가 아니라 실제 PostgreSQL에서 Durable Kernel 완료조건을 증명한다.

## 수정 파일

- 새 테스트: `tests/integration/test_durable_postgres.py`
- 필요 시 수정: `pyproject.toml` pytest marker 설정
- 필요 시 짧은 문서: `docs/development-postgres.md`

## 실행 전제

환경 변수:

- `ALL_TOMORROW_TEST_DATABASE_URL`

없으면 integration test는 명확히 skip.

CI/local에서 값이 있으면 실제 DB에 migration 적용 후 테스트.

별도 ORM/test framework를 추가하지 않는다.

## Test fixture

각 test run마다 고유 schema 또는 고유 DB namespace를 사용해 병렬 test 충돌 방지.

테스트 종료 후 정리.

migration은 실제 `PostgresStore.migrate("migrations")` 경로 사용.

## 필수 시나리오

### 1. Migration chain

0001 → 0002 → 0003 clean apply.

### 2. Restart persistence

Store instance A:

- Goal 생성
- Work enqueue
- Run 생성

close.

Store instance B 새로 생성:

- 같은 Goal/Work/Run 조회 가능

### 3. Durable claim

두 async claimant를 동시에 실행.

- 정확히 하나만 같은 Work 획득
- loser는 다른 Work 또는 None

### 4. Lease recovery

Work claim → executor crash를 heartbeat 중단으로 모사 → lease 만료 → recovery → 다시 claim 가능.

### 5. Multi-run lineage

하나의 Goal
→ 하나의 Work
→ Run 1 FAILED
→ Run 2 SUCCEEDED

모두 같은 Work와 trace로 조회 가능.

### 6. NEED_USER restart

Run이 NEED_USER
→ process/store 재생성
→ resume token answer
→ same run_id/current Work에서 RUNNING/계속 실행.

### 7. Atomic transition

강제로 Event INSERT 실패를 일으켜 Work/Run projection update도 rollback되는지 검증.

반대로 state UPDATE 실패 시 Event만 남지 않아야 한다.

### 8. Audit retention

Run 삭제/정리 시 Event가 cascade 삭제되지 않는지 확인.

실제 production에서 Run을 삭제할지와 별개로 FK invariant를 검증한다.

## 전체 regression

integration test 뒤 일반:

`python -m pytest -q`

도 통과해야 한다.

## 완료조건

위 8개 scenario + 기존 전체 test suite 통과.

완료 시:

- 이 파일 상태 → 개발완료
- `01-durable-kernel.md` 상태 → 개발완료
- stage index의 01 → 개발완료
- 02 Researcher Loop → 시작안했음 / 지금 시작 가능=예

AGENTS.md 규칙에 따라 같은 작업에서 index까지 갱신한다.
