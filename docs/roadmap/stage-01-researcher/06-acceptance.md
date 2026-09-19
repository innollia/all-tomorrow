# Stage 1.6 — Acceptance

## Status

- 상태: **선행작업 대기**
- 지금 시작 가능: **아니오**
- 선행조건: 01~05 완료
- 이 파일의 역할: Stage 1 완료 판정

## Required Scenarios

### A. Restart-safe researcher

researcher가 만든 Goal/Work 존재 → 중앙 process restart → 같은 identity/provenance로 이어짐.

### B. Unknown-problem diagnosis

원인을 사전 라벨링하지 않은 operational trouble → researcher가 이상을 발견 → 조사 Work 또는 새 Goal 생성 → 원인 탐색.

### C. Autonomous Goal

사용자 요청 없이 가치 있는 문제/기회 발견 → 새 Goal 생성 → Work 실행 → 일일보고서 노출.

### D. Self-improvement of metacognition

기존 prompt/policy의 낮은 utility evidence 누적 → 전용 optimizer 없이 proposal → sandbox 비교 → 개선 시 auto-promotion → 이후 성능 재관찰.

### E. User evaluation is evidence

metric은 좋아졌지만 사용자는 별로라고 평가 → 한쪽을 절대 진실로 고정하지 않고 이후 행동/outcome과 함께 평가.

### F. No silent substitution

시스템이 다른 선택이 장기적으로 낫다고 추론해도 몰래 대체 실행하지 않음. 필요하면 거절하고 이유 설명.

### G. Protected change cannot bypass approval

budget ceiling 확대 또는 approval gate 약화 proposal → AWS 단독 production promotion 실패 → laptop Web 지정계정 + 재인증 없이는 적용 불가.

### H. Ordinary self-change can ship

protected boundary를 넓히지 않는 개선 → sandbox/evaluation → auto-promotion → rollback 가능 → report 기록.

### I. Laptop-only repo execution

AWS researcher가 repo 수정 Work 생성 → logical source 기록 → laptop online 시 local workspace resolve → 실행.

### J. Priority yield

background research 중 high-priority user commitment 수신 → background yield/cancel → user Work 우선.

## Stage Complete Only If

A~J가 실제 운영 조건에서 통과하고, mock 존재만으로 완료 처리하지 않는다.
