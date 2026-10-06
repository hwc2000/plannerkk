# 계획 실행 중 데이터 계약

이 문서는 팀에서 흔히 “계획 실행 중 스키마”라고 부르는 **공유 객체 형식**을 정리한다. 관계형 DB 테이블 설계가 아니며, LangGraph 내부 `PlannerState` 전체를 다른 팀원이 그대로 사용할 필요도 없다.

- API·저장 객체: `camelCase`
- 그래프가 소유·정규화한 상태 필드: `snake_case`
- 실제 기준 코드: `server/app/adaptive/api.py`, `local.py`, `state.py`

`planning_context`처럼 외부 계약에서 받은 객체의 내부 키는 원래 계약을 유지한다.

## 무엇을 공유하는가

```text
A의 UserProfile/PlanningContext
            ↓ converter
      PlannerState (그래프 내부)
            ↑ 필드 매핑
B의 CheckIn/ExecutionRecord

그래프 결과 → RecoveryDraft 저장 → 사용자 승인 → 계획 반영
```

팀원이 직접 맞출 대상은 `CheckIn`, `ExecutionRecord`, `RecoveryDraft`와 API 요청·응답이다. `PlannerState`는 이 데이터를 받아 판단하는 내부 실행 상태다.

## CheckIn

`POST /api/adaptive/check-in`의 `checkIn`과 실행 기록 생성에 사용한다.

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `completed` | boolean | O | 작업 완료 여부 |
| `actualMinutes` | integer \| null | 선택 | 실제 사용 시간, 0 이상 |
| `remainingMinutes` | integer \| null | 선택 | 남은 작업 시간, 1 이상. 없으면 작업 전체 시간 사용 |
| `reasonCode` | string \| null | 선택 | 아래 이유 코드 |
| `note` | string | 선택 | 체크인 메모, 기본값 `""` |

`reasonCode` 값:

```text
time_shortage | task_too_large | fatigue | interruption
priority_changed | unclear_task | underestimated | other
```

## ExecutionRecord

현재는 로컬 SQLite의 실행 저장 상태 안 `executionRecords[]`에 저장한다. B의 공용 계약이 올라오면 이 객체를 경계에서 맞춘다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | string | 기록 ID |
| `planId` | string | 체크인 당시 계획 ID |
| `taskId` | string | 원래 작업 ID |
| `taskTitle` | string | 작업이 교체돼도 기록을 읽을 수 있도록 저장한 제목 |
| `plannedMinutes` | integer | 체크인 당시 계획 시간 |
| `actualMinutes` | integer \| null | 실제 사용 시간 |
| `remainingMinutes` | integer \| null | 남은 작업 시간 |
| `result` | `completed \| incomplete` | 실행 결과 |
| `reasonCode` | reasonCode \| null | 미완료 이유 |
| `note` | string | 사용자 메모 |
| `recoveryAction` | 아래 값 \| null | 복구 초안 처리 결과 |
| `createdAt` | ISO datetime string | UTC 기록 시각 |

`recoveryAction` 값:

```text
shrink | reschedule | keep_current_plan | plan_replaced | null
```

- 승인: 승인된 `strategy`
- 거절: `keep_current_plan`
- 새 계획으로 교체되어 초안 종료: `plan_replaced`
- 아직 결정되지 않음: `null`

## RecoveryDraft

승인 대기 중인 복구 초안이다. 현재 `recoveryDrafts[taskId]`에 작업별 최대 하나를 저장한다.

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `id` | string | 초안 ID |
| `planId` | string | 초안을 만든 계획 ID |
| `taskId` | string | 교체 대상 작업 ID |
| `recordId` | string | 연결된 `ExecutionRecord.id` |
| `strategy` | `shrink \| reschedule` | 현재 초안으로 생성·저장되는 복구 방법 |
| `checkIn` | CheckIn | 초안을 만든 체크인 |
| `draft` | RecoveryProposal | 사용자에게 보여줄 복구 내용 |
| `revisionCount` | integer | 수정 요청 누적 횟수 |

`RecoveryProposal`:

| 필드 | 타입 | 설명 |
| --- | --- | --- |
| `kind` | `shrink \| reschedule \| fit_deadline` | 초안 종류 |
| `replacesTaskId` | string | 교체 대상 작업 ID |
| `tasks` | DraftTask[] | 제안 작업 목록 |
| `appliedReasons` | string[] | 제안 이유 |
| `droppedScope` | string[] | 마감에 맞추며 제외한 범위 |
| `carryOverMinutes` | integer | 다음 계획으로 넘길 시간 |

`DraftTask`는 `title`, `minutes`, `doneWhen`, `start`, `end`를 가진다. `start`와 `end`는 코드가 배치하며 시간대 없는 현지 ISO 시각을 사용한다.

## API 계약

### 체크인

```json
{
  "revision": 3,
  "taskId": "task-1",
  "checkIn": {
    "completed": false,
    "actualMinutes": 20,
    "remainingMinutes": 30,
    "reasonCode": "time_shortage",
    "note": "예상보다 늦게 시작함"
  },
  "strategy": "reschedule",
  "consent": true,
  "events": []
}
```

### 초안 검토

```json
{
  "revision": 4,
  "draftId": "draft-1",
  "decision": "approve",
  "strategy": "reschedule",
  "feedback": null,
  "consent": false,
  "events": []
}
```

- `decision`: `approve | reject | revise`
- 승인할 때 `strategy`를 보내면 저장된 초안의 strategy와 같아야 한다.
- `events[]`: `{ "date": "YYYY-MM-DD", "startTime": "HH:mm", "endTime": "HH:mm" }`
- 응답 공통: `revision`, `recoveryDraft`, `result`
- 체크인 응답에는 `recordId`도 포함한다.

## PlannerState는 공유 DB 스키마가 아니다

`PlannerState`는 그래프 한 번 실행하는 동안 노드 사이에서 전달되는 내부 상태다. 주요 구분만 공유한다.

- 입력: `planning_context`, `execution_context`, `current_task`, `check_in`, `schedule_context`
- 진행: `route`, `strategy`, `draft`, `validation_errors`, 재시도 횟수
- 결과: `approval_status`, `fallback`, `error`, `profile_update_proposal`

상세 필드는 `server/app/adaptive/state.py`가 기준이다. 저장소가 SQLite에서 Supabase로 바뀌어도 DB 어댑터가 이 입력으로 변환하면 그래프 상태는 바꿀 필요가 없다.

## 현재 연결 상태

- A: 로컬 실행 프로필을 converter로 `execution_context`에 연결한다. A의 최종 `get_planning_context` 연결은 아직 남아 있다.
- B: 위 `ExecutionRecord` 임시 필드를 사용한다. B의 최종 공용 계약이 올라오면 필드 매핑을 맞춘다.
- DB: 현재 로컬 SQLite 한 행의 JSON 저장이다. Supabase 테이블·외래 키 설계는 이 문서의 범위가 아니다.
- `replan`과 그래프의 `new_plan`은 타입과 라우팅만 있으며 아직 연결되지 않았다. 현재 생성·승인 가능한 복구 초안은 `shrink`, `reschedule`뿐이다.
