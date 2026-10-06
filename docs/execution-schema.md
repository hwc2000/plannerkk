# B 담당 스키마

현재 구현 기준 공유용 규격입니다. 시간 단위는 분, 날짜는 UTC ISO 8601 문자열입니다.
`null`은 미입력 또는 미결정, `?`는 필드가 생략될 수 있음을 뜻합니다.
A의 UserProfile 2.0 및 프로필 승인 함수와 연결되어 있습니다.
사용자 구분은 A의 ExecutionStore 경계를 따르며 HTTP 인증 연결은 별도입니다.

## 1. ExecutionRecord — 실행 기록

```ts
type ExecutionRecord = {
  id: string
  planId: string
  taskId: string
  profileId: string
  taskTitle: string

  plannedMinutes: number
  actualMinutes: number | null
  remainingMinutes?: number | null

  result: "completed" | "partial" | "not_started" | "incomplete"
  reasonCode: ReasonCode | null
  note: string
  difficulty: number | null

  recoveryAction: string | null
  recoveryDecidedAt?: string
  createdAt: string
}

type ReasonCode =
  | "time_shortage"
  | "task_too_large"
  | "fatigue"
  | "interruption"
  | "priority_changed"
  | "unclear_task"
  | "underestimated"
  | "other"
```

| 필드 | 의미·조건 |
|---|---|
| `id` | 서버가 생성한 실행 기록 ID |
| `planId` | 연결된 계획 ID |
| `taskId` | 연결된 작업 ID |
| `profileId` | 계획 생성에 사용한 프로필 ID |
| `taskTitle` | 기록 시점의 작업 이름 |
| `plannedMinutes` | 기록 시점의 예정 시간 |
| `actualMinutes` | 실제 시간. 정수 0~1440 또는 null |
| `remainingMinutes` | 사용자가 예상한 남은 작업 시간. 정수 0~1440 또는 null. 실제−예정 시간으로 계산하지 않음 |
| `result` | 완료 / 부분 완료 / 미시작 / 상세 구분 없는 미완료 |
| `reasonCode` | 실패·지연 이유. partial과 not_started에서는 필수 |
| `note` | 메모. 최대 2,000자, 기본 빈 문자열 |
| `difficulty` | 난이도. 정수 1~5 또는 null |
| `recoveryAction` | 복구 방법·결정. 최대 1,000자 또는 null |
| `recoveryDecidedAt` | C의 복구 결정을 반영한 시각 |
| `createdAt` | 서버가 기록을 생성한 시각 |

미시작은 실제 시간 0만 허용합니다. 완료는 남은 시간 0 또는 null만 허용합니다.
C의 복구 결정은 `shrink`, `reschedule`, `keep_current_plan`, `plan_replaced`를 사용합니다.

| 이유 코드 | 의미 |
|---|---|
| `time_shortage` | 시간 부족 |
| `task_too_large` | 작업이 너무 큼 |
| `fatigue` | 피로 |
| `interruption` | 외부 방해 |
| `priority_changed` | 우선순위 변경 |
| `unclear_task` | 불명확한 작업 |
| `underestimated` | 시간 과소 추정 |
| `other` | 기타 |

## 2. ProfileUpdateProposal — 프로필 변경 후보

```ts
type ProfileUpdateProposal = {
  id: string
  profileId: string

  proposedChanges: {
    blockMinutes: {
      from: number
      to: number
    }
  }

  reason: string
  evidenceRecordIds: string[]
  ruleVersion: string

  status: "pending" | "approved" | "rejected"
  createdAt: string
  decidedAt: string | null
  appliedProfileId?: string
}
```

| 필드 | 의미 |
|---|---|
| `id` | 변경 후보 ID |
| `profileId` | 제안 대상 프로필 ID |
| `proposedChanges` | 변경 전후 값. 현재 planningPreferences.blockMinutes만 지원 |
| `reason` | 변경 제안 이유 |
| `evidenceRecordIds` | 근거 실행 기록 ID 목록 |
| `ruleVersion` | 후보 생성 규칙 버전 |
| `status` | 승인 대기 / 승인 / 거절 |
| `createdAt` | 후보 생성 시각 |
| `decidedAt` | 승인·거절 시각. 대기 중이면 null |
| `appliedProfileId` | 승인 후 적용된 프로필 ID. 승인 시에만 생성 |

후보 생성만으로 프로필을 변경하지 않습니다. 사용자 승인 후 A의
apply_profile_proposal을 호출하여 프로필 version 증가, learnedPatterns와
profileRevisions 저장, appliedProfileId 갱신을 같은 트랜잭션에서 처리합니다.

## 3. ExecutionSummary — 실행 요약

```ts
type ExecutionSummary = {
  revision: number
  days: number
  periodStart: string
  periodEnd: string
  planId: string | null
  profileId: string | null

  recordCount: number
  resultCounts: {
    completed: number
    partial: number
    not_started: number
    incomplete: number
  }
  completionRate: number | null

  plannedMinutes: number
  actualMinutes: number
  actualMinutesRecordCount: number
  minutesDifference: number

  incompleteReasonCounts: Record<ReasonCode, number>
  evidenceRecordIds: string[]
}
```

| 필드 | 의미·조건 |
|---|---|
| `revision` | 조회한 저장 상태 버전. A의 프로필 버전과 별개 |
| `days` | 조회 기간. 기본 14일, 정수 1~365 |
| `periodStart`, `periodEnd` | 조회 시작·종료 시각. 양 끝 포함, createdAt 기준 |
| `planId`, `profileId` | 조회 필터. null이면 해당 필터 미적용 |
| `recordCount` | 조회된 실행 기록 수 |
| `resultCounts` | 결과별 기록 수 |
| `completionRate` | 기록 중 completed 비율 0~100%, 소수 둘째 자리 반올림. 기록 없으면 null |
| `plannedMinutes` | 전체 조회 기록의 예정 시간 합계 |
| `actualMinutes` | 실제 시간이 입력된 기록의 실제 시간 합계 |
| `actualMinutesRecordCount` | 실제 시간이 입력된 기록 수 |
| `minutesDifference` | 실제 시간이 입력된 기록들의 실제−예정 시간 합계 |
| `incompleteReasonCounts` | 미완료 기록의 이유별 횟수. 이유 미입력 기록은 제외 |
| `evidenceRecordIds` | 집계에 사용한 기록 ID 목록. 생성 시각 순 |

미기록 작업은 완료율 분모에 포함하지 않습니다. 기록이 없으면 개수와 합계는 0,
근거 목록은 빈 배열입니다. 실행 요약은 관찰 데이터이며 승인된 프로필 변경이 아닙니다.

## 코드 위치

- 타입 정의: [types.ts](../src/shared/types.ts)
- 입력 검증·저장·요약: [execution_service.py](../server/app/execution_service.py)
- 변경 후보 생성: [execution_learning.py](../server/app/execution_learning.py)
- API·연동 설명: [execution-learning-loop.md](execution-learning-loop.md)

이 문서의 ReasonCode는 서버 허용값을 명확히 표현한 타입입니다.
현재 types.ts에서는 reasonCode를 string, 이유별 집계를 Record<string, number>로 선언합니다.
