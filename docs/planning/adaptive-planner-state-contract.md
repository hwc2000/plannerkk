# 팀원 C 계약: PlannerState와 연동 경계

이 문서는 **팀원 C가 소유하는 LangGraph `PlannerState`와 그래프 입출력 경계**를 설명한다.

- C가 소유: `PlannerState`, 계획 생성·복구 라우팅, `RecoveryDraft`, 검증, 승인 후 계획 반영
- A가 소유: `UserProfile`, `get_planning_context(user, project)`
- B가 소유: `ExecutionRecord`, `ProfileUpdateProposal`, 실행 기록 누적·패턴 감지·프로필 변경 제안

현재 `server/app/adaptive/local.py`의 `executionRecords` 저장과 `/api/adaptive/check-in`은 그래프를 독립적으로 검증하기 위한 **임시 로컬 어댑터**다. B의 최종 스키마와 API가 올라오면 B 구현을 사용하고 C 쪽 converter만 맞춘다. 이 문서는 B의 최종 `ExecutionRecord` 계약을 확정하지 않는다.

## 명명 규칙

- API·저장 객체: `camelCase`
- 그래프가 소유하고 정규화한 내부 상태: `snake_case`
- A·B가 제공한 외부 객체의 내부 키는 해당 팀원의 계약을 유지

## PlannerState

`PlannerState`는 DB 테이블이 아니라 **그래프 한 번 실행하는 동안 노드 사이에서 전달하는 임시 상태**다.

### 호출 입력

| 필드 | 의미 | 소유/출처 |
|---|---|---|
| `request` | `new_plan`, `replan`, `recovery`, `review` 요청 | C |
| `user_id` | 사용자 식별자 | 호출부 |
| `project_id` | 프로젝트 식별자 | 호출부 |
| `planning_context` | 사용자·프로젝트 계획 컨텍스트. 읽기 전용 | A |
| `execution_context` | 그래프가 판단에 필요한 값으로 정규화한 컨텍스트 | C converter |
| `profile_change_context` | 승인된 프로필 변경의 전후 값과 근거를 정규화한 재계획 입력 | B → C converter |
| `current_task` | 복구 대상 작업 | 현재 계획 |
| `check_in` | B의 실행 결과에서 변환한 이번 체크인 신호 | B → C converter |
| `schedule_context` | 현재 시각, 빈 시간, 마감 | 일정 시스템 |
| `base_revision` | 초안을 만들 때 읽은 계획 revision | 저장소 |
| `strategy` | 사용자가 직접 고른 복구 방법. 없으면 그래프가 판단 | 호출부 |

### 검토 입력

| 필드 | 의미 |
|---|---|
| `decision` | `approve`, `reject`, `revise` |
| `pending_draft` | 저장소에서 읽은 승인 대기 초안. 클라이언트가 원문을 보내지 않음 |
| `user_feedback` | 수정 요청 내용 |
| `revision_count` | 이 초안이 이미 수정된 횟수 |

### 그래프 진행 상태

| 필드 | 의미 |
|---|---|
| `route` | 선택된 그래프 경로 |
| `draft` | 작업 단위 복구 초안 |
| `plan_draft` | 전체 신규 계획·재계획 초안 |
| `validation_errors` | 코드 검증에서 발견한 오류 |
| `retry_count`, `retry_limit` | 제한된 재생성 횟수 |
| `min_task_minutes` | 시스템 최소 작업 길이 |
| `fit_limits` | 마감 안에 맞추기 위한 축소 한도 |

### 결과

| 필드 | 의미 |
|---|---|
| `approval_status` | `not_required`, `needs_input`, `waiting`, `approved`, `rejected`, `fallback` |
| `fallback` | 자동 처리하지 못했을 때 사용자에게 요청할 다음 선택 |
| `error` | 처리 실패 정보 |

코드 기준은 `server/app/adaptive/state.py`의 `PlannerState`다.

## A → C 경계

A의 `get_planning_context(user, project)` 결과를 `planning_context`로 받아 읽기만 한다. 그래프 판단에 자주 쓰는 값은 converter가 `execution_context`로 정규화한다.

```text
UserProfile + 프로젝트 + 가용시간 + 기억
    → A의 get_planning_context(...)
    → planning_context
    → C converter
    → execution_context
```

현재 로컬 프로필을 읽는 코드는 임시 어댑터다. A의 최종 계약이 정해져도 그래프 노드를 바꾸지 않고 converter만 바꾸는 것이 목표다.

## B → C 경계

B가 소유하는 `ExecutionRecord` 전체를 그래프 상태에 복제하지 않는다. 현재 복구 판단에 필요한 값만 `check_in`으로 변환한다.

```text
ExecutionRecord
    → C converter
    → check_in
        completed
        actual_minutes
        remaining_minutes
        reason_code
        note
```

`ExecutionRecord`의 최종 필드, 저장 API, 반복 패턴 감지, `ProfileUpdateProposal` 생성·승인은 B의 범위다. C는 다음 값만 필요로 한다.

- 어떤 작업의 실행 결과인지
- 완료 여부와 실제/남은 시간
- 지연·실패 이유
- 승인된 복구 전략을 `recoveryAction`으로 돌려줄 방법
- 승인된 `ProfileUpdateProposal`을 전달받을 방법

```text
ProfileUpdateProposal (camelCase, B 소유)
    → profile_change_context (snake_case, C 소유)
        before
        after
        changed_fields
        reason
        evidence_record_ids
        source_profile_id
        applied_profile_id
```

외부 제안 객체를 `PlannerState`에 그대로 넣지 않는다. 현재 로컬 변환기는
`adaptive/local.py::profile_change_context_from_proposal`이고, 공용 검증 경계는
`adaptive/context.py::to_profile_change_context`다.

## C가 생성하는 RecoveryDraft

복구 초안은 C의 계획 변경 제안이며 승인 전에는 실제 계획을 바꾸지 않는다.

```text
RecoveryDraft
- id
- taskId
- strategy        # shrink | reschedule
- baseRevision
- proposal
- revisionCount
- createdAt
- recordId        # 임시 로컬 어댑터에서 B 기록과 연결
```

`proposal`은 C가 생성·검증한 계획 작업 목록과 적용 근거를 포함한다. 승인 시 현재 시각·빈 시간·revision을 다시 검사하고 통과한 경우에만 계획에 반영한다.

## 현재 API의 성격

```text
POST /api/adaptive/check-in
POST /api/adaptive/review
```

두 API는 현재 C 그래프의 체크인→복구 초안→검토 흐름을 `/docs`에서 끝까지 시험하기 위한 로컬 통합 API다.

- `/api/adaptive/check-in`의 실행 기록 저장 부분은 B 최종 API가 아니다.
- `/api/adaptive/review`의 계획 초안 검토·반영 부분은 C 범위다.
- B 구현이 합쳐지면 실행 기록은 B 저장 경계를 호출하고, C는 변환된 입력을 받아 그래프를 실행한다.

## 전체 재계획과 승인

프로필 변경 제안 승인은 프로필만 먼저 원자적으로 갱신한다. 확정 계획은 즉시
교체하지 않는다. 계획이 있으면 화면이 승인 응답의 새 revision으로
`POST /api/execution/plan`을 다시 호출하고 `profileChangeProposalId`를 전달한다.

그래프의 `replan` 경로는 정규화한 `profile_change_context`와 `planning_context`를
full-plan generator에 전달하고, 결과를 `plan_draft`로 반환한다. 저장 어댑터는 이를
기존 `planDraft`에 저장한다. 사용자는 기존 `/plan/confirm` 또는 `/plan/discard`로
검토하며, 확정 전에는 기존 계획이 유지된다. 완료된 작업은 재계획 초안에도 그대로
보존하고 그 시간은 새 작업 배치에서 제외한다.

`profileId`는 사용자 ID가 아니라 계획 생성에 사용한 프로필 **버전 ID**다.
`user_id`는 소유자, `project_id`는 업무 범위다. 현재 로컬 저장소는 아직 단일 사용자
구조이며 다중 사용자 격리나 인증을 구현한 것으로 해석하지 않는다.

## 현재 연결 상태

- 연결됨: `new_plan`, 승인된 프로필 변경의 전체 `replan`, `recovery`의 `shrink`·`reschedule`, 승인·거절·수정, 승인 시 재검증
- 변환 경계: B `ProfileUpdateProposal` → C `profile_change_context`
- 미연결: 인증 기반 `user_id`, A·B 최종 공용 저장 계약

## 로컬 저장소

현재 SQLite는 `execution_state(id, document)` 한 행의 JSON 문서 방식이다. `executionRecords`와 `recoveryDrafts`는 로컬 통합 테스트용 저장값이며 공용 관계형 DB 스키마가 아니다.

기존 로컬 테스트 데이터를 유지할 필요가 없다면 서버를 끄고 다음 파일을 삭제한 뒤 다시 실행한다.

```text
data/replan.sqlite3
```

`REPLAN_DB_PATH`를 설정했다면 그 경로의 파일을 삭제한다.
