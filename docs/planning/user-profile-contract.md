# A 담당: 사용자 프로필·설문·계획 컨텍스트

최종 갱신: 2026-10-06. 현재 로컬 구현 기준이며 원격 main의 배포 상태를 뜻하지 않는다.
기준 문서: `adaptive-planner-state-contract.md`, B PR #8 (참조 당시 head `c4c2a84`). B 전체 구현은 병합하지 않았다.
API/DB는 camelCase, C 그래프 내부는 snake_case를 유지한다.

## 현재 사용자 흐름

**선택형 설문 → 프로필 초안 검토 → 프로필 확정 → 가용시간 선택 → 주간 목표 입력** 순서다.

- `ProfileForm`의 4단계 설문을 사용한다. 답변은 체크박스와 라디오 버튼으로 선택한다.
- 프로필 작성은 API 키 없이 가능하다. `/profile`에 `mode: "demo", consent: false`로 전송하며 서버 규칙으로 선호와 요약을 계산한다. demo는 임시 저장이라는 뜻이 아니며 초안과 확정본 모두 DB에 저장한다.
- 기존 프로필은 **설문 수정**에서 초안 또는 확정본의 답변을 불러와 수정한다. 새 초안을 확정하기 전까지 기존 확정본은 유지한다.
- 프로필 작성은 규칙 기반으로 처리한다. 주간 계획/일반 AI 계획 생성은 LLM 호출과 전송 동의를 사용한다.

## 설문 항목

| 단계 | 항목 | 입력 방식 |
|---|---|---|
| 1. 생활의 리듬 | roles, regularity | 생활 형태 복수 선택, 생활 규칙성 단일 선택 |
| 2. 막히는 순간 | barriers | 계획이 무너지는 이유 복수 선택 |
| 3. 집중 습관 | focusMinutes, energy | 한 번의 집중 시간과 집중이 잘되는 시간대 각각 단일 선택 |
| 4. 다시 시작하는 방법 | recovery, scheduleStyle | 계획이 틀어졌을 때 대응과 선호 계획 방식 각각 단일 선택 |

- roles/barriers는 체크박스, 나머지는 라디오 버튼이다. barriers의 none/unknown은 다른 항목과 함께 선택할 수 없다.
- focusMinutes 선택값은 15, 25, 30, 45, 50, 60, 90분 또는 null(아직 모름)이다. 하루 집중 횟수나 하루 전체 가용시간을 묻지 않는다.
- 단계별 필수 선택을 검사한 뒤 다음 단계로 이동한다. focusMinutes의 기본값은 null, scheduleStyle의 기본값은 unknown이다.
- `dailyMinutes`는 현재 설문에서 받지 않고 제출 시 null로 설정한다. 타입/기존 데이터 호환을 위해 스키마에는 남긴다.
- `constraints`, `context` 입력 UI는 없다. 신규 설문은 빈 문자열을 사용한다. 기존 프로필 수정 시 기존 값은 보존하되 새로운 자유 텍스트를 입력받지 않는다.
- 요약에서 dailyMinutes는 표시하지 않는다. 답변을 검토한 뒤 확정하며 언제든 설문 수정으로 돌아갈 수 있다.

## 가용시간과 계획 방식

가용시간은 프로필 안에서 선택하지 않는다. 확정 후 별도 영역에서 요일별 시간을 선택한다.
저장된 시간이 있으면 수정 영역은 기본적으로 접히며, 미설정이면 펼쳐진다.
`settings.slots`에 저장한 시간을 다음 계획에서도 재사용한다. 프로필의 focusMinutes는 한 번의 집중 길이이고 slots는 실제 배치 가능한 시간이다.

프로필 확정 시 scheduleStyle에 따라 `settings.view`를 time_blocks → timeline, flexible_queue → checklist로 맞춘다.
별도 화면에서 같은 계획 방식을 다시 선택하도록 요구하지 않는다.
고정 일정 텍스트는 자동 차감하지 않는다. 배치할 수 없는 시간은 가용시간 선택에서 제외하거나 캘린더 일정으로 등록해야 한다.

## 스키마

정의 위치: `server/app/user_profile.py`, `server/app/execution_profile.py`, `server/app/execution_api.py`. 프론트엔드 타입은 `src/shared/types.ts`, 프로필 JSON Schema는 `user-profile.schema.json`이다.
아래 필수 여부와 기본값은 **Pydantic 모델 기준**이다. 필수이면서 nullable인 필드는 키를 포함하고 null을 사용할 수 있다는 뜻이다. 원본 API의 answers는 dict로 받은 뒤 `validate_answers`로 정규화하므로 일부 생략값은 null/빈 문자열로 보완된다. 현재 설문 화면은 모든 답변 키를 전송한다.

### 구조 관계

```text
execution_state / user_execution_state 의 JSON document
├─ profileDraft: UserProfile | null
├─ profile: UserProfile | null
│  ├─ declaredFacts: SurveyAnswers
│  ├─ facts: declaredFacts와 동일한 호환용 사본
│  ├─ planningPreferences: PlanningPreferences
│  ├─ insights: 요약·전략·참고 질문
│  └─ learnedPatterns: LearnedPattern[]
├─ surveyResponses[] ← profile.surveyResponseId로 연결
├─ profileRevisions[] → 확정 시점의 UserProfile 전체 snapshot
└─ settings: { slots: Slot[], view }
```

각 배열은 별도 SQL 테이블이 아니라 사용자별 상태 JSON 안의 컬렉션이다. 가용시간은 UserProfile 필드가 아니다.

### UserProfile — 최상위 프로필

| 필드 | 타입·허용값 | 필수 / 기본값 | 검증 조건 |
|---|---|---|---|
| `id` | string | 필수 | — |
| `userId` | string | 필수 | — |
| `schemaVersion` | `2.0` | "2.0" | — |
| `version` | integer | 필수 | 최솟값 1 |
| `status` | `draft`, `confirmed` | 필수 | — |
| `source` | `demo`, `llm` | 필수 | — |
| `declaredFacts` | object | 필수 | — |
| `facts` | object | 필수 | — |
| `planningPreferences` | PlanningPreferences | 필수 | — |
| `insights` | object | 필수 | — |
| `learnedPatterns` | 배열(LearnedPattern) | [] | — |
| `surveyResponseId` | string / null | null | — |
| `createdAt` | string | 필수 | — |
| `updatedAt` | string | 필수 | — |
| `confirmedAt` | string / null | null | — |

- id는 서버에서 생성하는 식별자다. source는 현재 설문에서 demo를 사용한다. llm은 기존 저장값과의 호환용 허용값이다.
- version은 프로필 확정/승인마다 증가하며 상태 전체의 revision과 다르다. 초안은 다음 확정 버전을 사용한다.
- declaredFacts는 dict 타입이지만 별도 SurveyAnswers 검증을 수행한다. facts는 declaredFacts와 정확히 같아야 한다.
- confirmed 상태는 planningPreferences.status=confirmed 및 비어 있지 않은 confirmedAt이 필요하다.
- 날짜 필드는 모델에서 string으로 선언되어 있다. 서버는 UTC ISO 8601로 생성하지만 이 모델 자체가 모든 날짜 문자열의 형식을 검증하지는 않는다. ID도 UUID 전용 타입이 아니다.
- insights와 proposedChanges는 dict이므로 JSON Schema만으로 내부 의미 검증이 완료되지 않는다. 아래 생성/검증 함수 조건을 함께 따른다.

### SurveyAnswers — 명시적 설문 응답

| 필드 | 타입·허용값 | 필수 / 기본값 | 검증 조건 |
|---|---|---|---|
| `roles` | 배열(`student`, `employee`, `job_seeker`, `freelancer`, `other`) | 필수 | 최소 항목 1 |
| `regularity` | `regular`, `mixed`, `irregular`, `unknown` | 필수 | — |
| `barriers` | 배열(`starting`, `overplanning`, `distraction`, `fatigue`, `interruptions`, `unclear`, `none`, `unknown`) | 필수 | 최소 항목 1 |
| `focusMinutes` | integer / null | 필수 | 최솟값 5, 최댓값 180 |
| `dailyMinutes` | integer / null | 필수 | 최솟값 5, 최댓값 720 |
| `energy` | `morning`, `afternoon`, `evening`, `variable`, `unknown` | 필수 | — |
| `recovery` | `replan`, `reduce`, `continue`, `abandon`, `unknown` | 필수 | — |
| `constraints` | string | 필수 | 최대 글자 1500 |
| `context` | string | 필수 | 최대 글자 1500 |
| `scheduleStyle` | `time_blocks`, `flexible_queue`, `unknown` | "unknown" | — |

- roles/barriers는 비어 있지 않아야 하며 중복값을 허용하지 않는다. barriers의 none/unknown은 단독 선택만 가능하다.
- focusMinutes/dailyMinutes는 엄격한 정수 또는 null이다. 숫자 문자열이나 boolean을 시간으로 받지 않는다.
- constraints/context는 공백을 제거하여 정규화한다. 현재 신규 설문에서는 빈 문자열이며 입력 화면은 제공하지 않는다.
- 현재 UI의 focusMinutes 선택지는 15/25/30/45/50/60/90/null이다. 서버 허용 범위 5~180과 구분한다.
- 현재 제출에서는 dailyMinutes=null이다. scheduleStyle 생략은 기존 입력 호환을 위해 허용하지만 신규 설문은 unknown 또는 명시적 선택을 보낸다.

### PlanningPreferences — 계산된 계획 선호

| 필드 | 타입·허용값 | 필수 / 기본값 | 검증 조건 |
|---|---|---|---|
| `blockMinutes` | integer | 필수 | 최솟값 1, 최댓값 180 |
| `breakMinutes` | integer | 필수 | 최솟값 0, 최댓값 60 |
| `bufferPercent` | integer | 필수 | 최솟값 0, 최댓값 90 |
| `dailyPlannedMinutes` | integer / null | null | 최솟값 1, 최댓값 720 |
| `scheduleStyle` | `time_blocks`, `flexible_queue` | 필수 | — |
| `scheduleStyleSource` | `user`, `rule`, `legacy` | "legacy" | — |
| `recoveryPreference` | `replan`, `reduce`, `continue`, `abandon`, `unknown` | 필수 | — |
| `starterMinutes` | integer / null | null | 최솟값 1, 최댓값 180 |
| `status` | `provisional`, `confirmed` | 필수 | — |

#### 항목 간 조건과 생성 규칙

- blockMinutes ≤ dailyPlannedMinutes(하루 예산이 있는 경우), starterMinutes ≤ blockMinutes(시작 작업이 있는 경우).
- 초기 blockMinutes = min(focusMinutes 또는 15, dailyMinutes 또는 180, 50). distraction 응답이면 최대 20분이다.
- breakMinutes=5. 불규칙/모름 또는 overplanning이면 bufferPercent=40, 나머지는 25다.
- dailyMinutes가 있으면 dailyPlannedMinutes=int(dailyMinutes × (100-bufferPercent)/100), 없으면 null이다. 예산이 있으면 집중 구간과 시작 작업을 그 안으로 줄인다.
- starting 응답이 있으면 starterMinutes=min(5, blockMinutes), 없으면 null이다.
- recoveryPreference는 설문 recovery를 따른다. scheduleStyle 명시 선택은 user, 규칙으로 계산한 값은 rule, 기존 값의 출처 보완은 legacy다.
- 초안의 선호 status는 provisional이며 사용자가 프로필을 확정하면 confirmed가 된다.

### LearnedPattern — 승인된 실행 관찰

| 필드 | 타입·허용값 | 필수 / 기본값 | 검증 조건 |
|---|---|---|---|
| `id` | string | 필수 | — |
| `observation` | string | 필수 | 최소 글자 1, 최대 글자 2000 |
| `proposedChanges` | object | 필수 | — |
| `evidenceRecordIds` | 배열(string) | 필수 | 최소 항목 1 |
| `approvedProposalId` | string | 필수 | — |
| `projectId` | string / null | null | — |
| `status` | `active`, `revoked`, `superseded` | "active" | — |
| `approvedAt` | string | 필수 | — |
| `expiresAt` | string / null | null | — |

- proposedChanges의 현재 승인 적용 경계는 `{"blockMinutes":{"from":25,"to":20}}` 형태만 지원한다.
- evidenceRecordIds는 기존 실행 기록을 참조하고 approvedProposalId는 승인된 변경 제안을 참조한다. 단순히 문자열이 있다고 유효한 승인으로 보지 않는다.
- projectId=null이면 공통 범위, expiresAt=null이면 명시된 만료 시각이 없다. 컨텍스트 로더는 승인 상태·범위·시간을 추가 검사한다.
- 새 제안 승인 시 이전 active 패턴은 superseded로 변경한다. 모델은 revoked도 허용하지만 현재 화면에서 별도 철회 기능을 제공한다는 뜻은 아니다.

### insights — 요약과 추천 설명

| 필드 | 타입 | 생성·검증 계약 |
|---|---|---|
| summary | string | 요약. validate_insights 사용 시 1~2000자 |
| strategies | 배열 | 전략 목록. validate_insights 사용 시 1~6개 |
| strategies[].action | string | 추천 행동, 1~1500자 |
| strategies[].reason | string | 추천 이유, 1~1500자 |
| strategies[].evidence | string[] | 비어 있지 않은 설문 필드명 목록 |
| followUpQuestions | string[] | 참고 질문. 최대 4개, 각 1~500자 |

근거 필드명은 roles, regularity, barriers, focusMinutes, dailyMinutes, energy, recovery, constraints, context, scheduleStyle 중 하나다.
현재 설문은 generate_profile의 규칙으로 insights를 생성한다. UserProfile 모델의 insights는 dict이며 위 길이/개수 제한은 validate_insights 함수의 조건이다. 이 함수를 호출하지 않는 저장 경로까지 같은 검증을 보장한다고 해석하지 않는다.
followUpQuestions는 저장되는 참고 설명이며 설문 단계나 별도의 답변 API가 아니다. dailyMinutes=null일 때 현재 규칙 생성기는 하루 가용시간 관련 참고 질문을 포함할 수 있지만 실제 가용시간 입력은 확정 후 settings에서 진행한다.

### 원본 설문 — surveyResponses[]

| 필드 | 타입 / 기본값 | 의미 |
|---|---|---|
| id | string, 서버 생성 | 원본 설문 ID |
| userId | string | 저장소의 사용자 |
| surveyVersion | string, `1.1` | 설문 버전. 프로필 구조 버전 2.0과 별개 |
| answers | object | 제출된 원본 응답의 복사본. 정규화된 declaredFacts와 구분 |
| submittedAt | string | 서버 생성 UTC ISO 8601 |

save_profile_draft가 제출마다 새 원본을 추가하고 profileDraft.surveyResponseId로 연결한다. 이 컬렉션에는 별도 Pydantic 모델이 없으며 저장 함수가 구조를 만든다.

### 프로필 이력 — profileRevisions[]

| 필드 | 타입 | 의미 |
|---|---|---|
| version | integer | 해당 확정본 버전 |
| profileId | string | 해당 프로필 ID |
| source | string | survey_confirmed / proposal_approved / legacy_snapshot |
| sourceId | string 또는 null | 원본 설문/승인 제안 ID. 복원된 기존 스냅샷은 null |
| createdAt | string | 해당 프로필 updatedAt |
| snapshot | UserProfile | 그 시점의 프로필 전체 복사본 |

초안 생성만으로 확정 이력을 추가하지 않는다. 원본 없는 기존 자료는 legacy_snapshot으로 구분한다. 이 컬렉션은 저장 함수가 만드는 dict 구조다.

### 가용시간 — PlannerSettings / Slot

| 필드 | 타입 | 필수 / 기본값 | 검증 |
|---|---|---|---|
| settings.slots | Slot[] | 요청 필수, 초기 상태 [] | 최대 105개, 동일 day/hour 중복 불가 |
| settings.view | string | 요청 필수, 초기 timeline | timeline / checklist |
| slots[].day | integer | 필수 | 엄격한 정수 0~6, 월요일=0·일요일=6 |
| slots[].hour | integer | 필수 | 엄격한 정수 8~22, 해당 시각부터 1시간 |

예: day=0, hour=18은 월요일 18:00~19:00이다. 22는 22:00~23:00이다. 30분 단위 선택 구조가 아니다. API 요청 revision은 0 이상 엄격한 정수이며 낡은 revision은 409를 반환한다.
명시된 네 Pydantic 프로필 모델과 PlannerSettings/Slot은 extra=forbid다. 임의 필드를 추가할 수 없지만 dict로 선언한 내부 필드에는 별도 검증 범위가 적용된다.

### 저장 JSON 예시

아래는 새 설문 → 초안 → 확정으로 만든 예시이며 실제 사용자 데이터가 아니다. 예시를 짧게 유지하기 위해 원본 설문·이력 배열은 별도로 보여준다.

```json
{
  "id": "profile-example-1",
  "userId": "local",
  "schemaVersion": "2.0",
  "version": 1,
  "status": "confirmed",
  "source": "demo",
  "declaredFacts": {
    "roles": [
      "student"
    ],
    "regularity": "regular",
    "barriers": [
      "starting"
    ],
    "recovery": "reduce",
    "energy": "evening",
    "focusMinutes": 25,
    "dailyMinutes": null,
    "constraints": "",
    "context": "",
    "scheduleStyle": "flexible_queue"
  },
  "facts": {
    "roles": [
      "student"
    ],
    "regularity": "regular",
    "barriers": [
      "starting"
    ],
    "recovery": "reduce",
    "energy": "evening",
    "focusMinutes": 25,
    "dailyMinutes": null,
    "constraints": "",
    "context": "",
    "scheduleStyle": "flexible_queue"
  },
  "planningPreferences": {
    "blockMinutes": 25,
    "breakMinutes": 5,
    "bufferPercent": 25,
    "dailyPlannedMinutes": null,
    "scheduleStyle": "flexible_queue",
    "scheduleStyleSource": "user",
    "recoveryPreference": "reduce",
    "starterMinutes": 5,
    "status": "confirmed"
  },
  "insights": {
    "summary": "답변을 바탕으로 만든 첫 실행 프로필입니다. 제안한 시간과 여유분은 실제 실행 후 조정할 초기값입니다.",
    "strategies": [
      {
        "action": "첫 집중 구간을 25분으로 시도해 보세요.",
        "reason": "응답한 집중 시간과 하루 여유 시간을 상한으로 둔 초기 제안입니다. 모르는 경우 15분부터 탐색합니다.",
        "evidence": [
          "focusMinutes",
          "dailyMinutes"
        ]
      },
      {
        "action": "첫 행동을 5분 이내로 줄이기",
        "reason": "시작이 어렵다는 응답에 맞춰 준비와 첫 행동을 분리합니다.",
        "evidence": [
          "barriers"
        ]
      }
    ],
    "followUpQuestions": [
      "필수 일정을 제외하고 하루에 확보할 수 있는 시간은 어느 정도인가요?"
    ]
  },
  "learnedPatterns": [],
  "surveyResponseId": "survey-example-1",
  "createdAt": "2026-10-06T07:00:00+00:00",
  "updatedAt": "2026-10-06T07:00:00+00:00",
  "confirmedAt": "2026-10-06T07:00:00+00:00"
}
```

```json
{
  "surveyResponses": [
    {
      "id": "survey-example-1",
      "userId": "local",
      "surveyVersion": "1.1",
      "answers": {
        "roles": [
          "student"
        ],
        "regularity": "regular",
        "barriers": [
          "starting"
        ],
        "focusMinutes": 25,
        "dailyMinutes": null,
        "energy": "evening",
        "recovery": "reduce",
        "constraints": "",
        "context": "",
        "scheduleStyle": "flexible_queue"
      },
      "submittedAt": "2026-10-06T07:00:00+00:00"
    }
  ],
  "settings": {
    "slots": [
      {
        "day": 0,
        "hour": 18
      },
      {
        "day": 2,
        "hour": 19
      }
    ],
    "view": "checklist"
  }
}
```

이력의 snapshot에는 위 UserProfile 전체가 들어가며 version=1, profileId=profile-example-1, source=survey_confirmed, sourceId=survey-example-1로 연결된다.

## 시간 지정형과 작업량 지정형

새 응답 필드 `answers.scheduleStyle`:

- `time_blocks`: 특정 시각을 정하는 계획. 예: 18:30~19:00 공부.
- `flexible_queue`: 작업별 소요량을 정하는 계획. 예: A 60분, B 120분.
- `unknown` 또는 기존 응답에서 생략: 규칙성이 있으면 time_blocks, 아니면 flexible_queue를 **초안으로만** 제안.

명시적 선택이 생활 규칙성에 따른 계산보다 우선한다.
`planningPreferences.scheduleStyleSource`는 user / rule / legacy로 출처를 구분한다.
확정 전에는 계획 컨텍스트에 들어가지 않는다.
실제 시작/종료 시각은 `ExecutionEntry.start/end`, 소요량은 `minutes`에 둔다.
프로필에 이번 작업의 18:30 같은 시각을 저장하지 않는다.

기존 주간 플래너의 style별 프롬프트와 작업 크기 계산을 유지한다.
계획에 scheduleStyle/profileVersion을 저장하므로 나중에 프로필을 바꿔도 기존 계획의 표시 기준은 유지된다.
작업량 지정형은 실행 화면에서 시각을 숨기고 소요량을 표시한다.
현재 캘린더/충돌 검사용 내부 배치는 기존 스케줄러를 계속 사용한다. 완전한 무시각 작업 큐로 C 그래프를 바꾸는 작업은 포함하지 않는다.

## 프로필 초기화

**프로필 초기화하기**는 확인창 후 `/api/execution/profile/reset`을 호출한다.

| 처리 | 대상 |
|---|---|
| null로 초기화 | profile, profileDraft, planDraft |
| 빈 배열로 초기화 | profileConversations, surveyResponses, profileRevisions, profileUpdateProposals |
| 유지 | settings, plan, executionRecords, recoveryDrafts, memories |

revision을 검사하고 한 트랜잭션으로 처리한다. 성공하면 설문 첫 단계로 돌아간다.
이전 확정 계획은 과거 프로필을 참조할 수 있다. 가용시간·확정 계획까지 초기화하는 `/api/execution/reset`과 구분한다.

## 현재 화면이 사용하는 API

```text
POST /api/execution/profile                   {revision, answers, mode: "demo", consent: false} → 초안
POST /api/execution/profile/confirm           {revision} → 확정
POST /api/execution/profile/reset             {revision} → 프로필 관련 정보 초기화
POST /api/execution/reset                     {revision} → 실행 상태 전체 초기화
GET  /api/execution/profile                   확정 프로필
GET  /api/execution/survey-responses           원본 설문 이력
GET  /api/execution/profile/revisions          확정본 스냅샷 이력
PUT  /api/execution/settings                  {revision, settings} → 가용시간 저장
POST /api/execution/planning-context          WeeklyRequest → 공통 컨텍스트
```

모든 쓰기는 revision을 검사하고 SQLite 트랜잭션으로 처리한다. 충돌은 409다.
프로필 확정은 planDraft를 무효화하지만 확정된 과거 계획은 보존한다.
재설문으로 만든 새 확정본은 최신 응답을 사용하며 과거 패턴은 변경 이력에 남는다. 프로필 초기화는 이 이력도 삭제한다.

## A → C 컨텍스트

```python
planning = get_planning_context(store.user_id, project, state=store.read(), memories=memories)
# C: planning_context = planning (read only)
# C converter: planning['userProfile'] → execution_context
```

반환 필드: schemaVersion, userId, profileId, profileVersion, generatedAt,
userProfile(declaredFacts/planningPreferences/learnedPatterns), projectContext,
availability(timezone/slots), memories, warnings.

승인된 프로필만 로드한다. active + 승인 근거 존재 + 미만료 + 프로젝트 범위 일치 패턴만 포함한다.
Memory는 user/ai_approved 출처, 민감하지 않음, 계획 사용 허용, 미만료,
최근 180일 이내 갱신, 사용자/프로젝트 범위 일치를 모두 만족해야 한다.
프로필의 자유 텍스트 constraints/context는 기본적으로 계획 LLM에 전송하지 않는다.
명시적 시간 제약은 가용 시간표/캘린더, 계획에 사용할 문장은 허용된 Memory로 전달한다.
이 정책은 민감 정보를 자동 판별하는 기능이 아니다. Memory의 sensitive/useForPlanning 메타데이터를 사용한다.

주간 계획, 일반 AI 초안, C 복구 어댑터가 공통 로더를 사용한다.
일반 AI 초안은 기존 호환성을 위해 프로필 없는 일반 계획도 지원하며, 프로필이 있으면 같은 컨텍스트를 전달한다.
프로필 기반 주간 계획과 C 복구는 프로필이 없으면 거절한다.
Memory/Project는 기존 브라우저 저장 구조를 유지하며 요청으로 전달한다.

## B PR #8 통합 경계

B의 ExecutionRecord/ProfileUpdateProposal 필드는 변경하지 않는다.
B의 승인 API에서 **기존 직접 prefs 수정 블록 대신** 아래 함수를 store.change 내부에서 호출한다.

```python
from .user_profile import apply_profile_proposal

def update(state):
    if decision == 'approve':
        apply_profile_proposal(
            state, proposal_id,
            expected_version=state['profile']['version'],
        )
        return
    # B의 기존 reject 분기 유지

return store.change(revision, update)
```

함수는 저장된 pending 제안만 받아 profileId, 버전, 변경 전 값, 근거 기록을 검증한다.
blockMinutes만 지원(PR #8 계약). 승인되면 프로필 ID 회전, version 증가,
learnedPatterns/스냅샷 저장, proposal approved/appliedProfileId 기록을 같은 트랜잭션에서 수행한다.
중복 승인이나 오래된 프로필은 거절한다. C 그래프는 프로필을 직접 수정하지 않는다.
B의 서비스/엔드포인트 자체는 PR #8 병합 시 위 한 경계로 연결해야 한다.

## 저장·마이그레이션

기본 로컬 사용자는 기존 execution_state(id=1, document)를 유지한다.
다른 사용자 저장소는 ExecutionStore(path, user_id='...')로 만들고 user_execution_state에 분리 저장한다.
HTTP 서버는 여전히 로컬 단일 사용자용이다. userId를 외부 요청에서 받지 않는다.
다중 사용자 서비스 배포 시 인증된 사용자로 저장소를 주입하고 프로젝트/기억 소유권을 검증해야 한다.

기존 프로필은 읽기 시 호환 보완, 다음 쓰기 시 저장한다. 기존 ID/승인 상태/계획을 유지한다.
기존 facts는 원본 설문이라고 꾸미지 않고 legacy_snapshot으로만 기록한다.
기존 draft는 승격하지 않는다. 키·사용자 DB를 테스트/커밋에 포함하지 않는다.

## 검증

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s server/tests -q
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc -b
node node_modules/vite/bin/vite.js build
```

2026-10-06 마지막 실행 기록: 백엔드 151개 통과(설문 화면 전환 직전), 프론트엔드 25개 통과(전환 후). 타입 검사와 프로덕션 빌드도 전환 후 통과했다.
현재 UI 검증에는 설문 기본 진입 시 네트워크 호출 없음, 체크한 답변의 demo 제출, 복수 선택, 프로필 초기화가 포함된다.
서버 검증에는 사용자 분리, 버전/승인/원본 이력, 컨텍스트 필터, 레거시 보존이 포함된다.
이 문서 갱신만으로 테스트를 다시 실행한 것은 아니다.

## 주요 구현 파일

- `src/features/execution/ProfileForm.tsx`: 현재 4단계 선택형 설문
- `src/features/execution/ExecutionView.tsx`: 설문 진입·요약·확정·수정·초기화 및 확정 후 가용시간
- `src/features/execution/AvailabilityGrid.tsx`: 요일별 가용시간 선택
- `src/features/execution/profileLabels.ts`: 항목 이름과 선택지
- `server/app/execution_profile.py`: 설문 검증 및 규칙 기반 선호/요약 생성
- `server/app/user_profile.py`: A 스키마, 버전 이력, 확정, B 승인 적용 경계
- `server/app/execution_api.py`: 프로필·설정·계획 API
- `server/app/execution_store.py`: 사용자별 저장 및 레거시 호환
- `server/app/planning_context.py`: A 공통 컨텍스트와 필터
- `server/app/execution_llm.py`: 계획 생성용 LLM 호출
- `src/shared/types.ts`, `docs/planning/user-profile.schema.json`: 타입 및 스키마 계약
