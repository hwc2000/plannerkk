# 적응형 플래너 그래프 (팀원 C)

A의 사용자 컨텍스트와 B의 실행 결과를 받아 계획 생성·재계획·승인 흐름을 제어한다.
코드: `server/app/adaptive/`
- `state.py` 그래프 실행 상태 · `graph.py` 그래프 · `context.py` 변환 경계 · `ports.py` 생성기·저장소 경계
- `llm_generator.py` 실제 LLM 축소 생성기 · `local.py` 로컬 DB 어댑터 · `api.py` `/api/adaptive/*`
팀원 C의 State 계약과 연동 경계: [adaptive-planner-state-contract.md](adaptive-planner-state-contract.md)

> 이 문서의 소유 범위는 팀원 C의 `PlannerState`, 계획 생성·복구, 검증·승인 흐름이다. A의 `UserProfile`과 B의 `ExecutionRecord`·`ProfileUpdateProposal`은 각 담당자가 확정하며, 현재 코드는 독립 검증용 임시 어댑터만 제공한다.

## 체크인 흐름 (API)

```text
POST /api/adaptive/check-in   작업 하나의 실행 결과
  → 실행 기록(executionRecords) 저장
  ├─ 완료   → 작업 완료 처리 (AI 호출 없음)
  └─ 미완료 → 그래프(recovery) → 승인 대기 초안이 생기면 작업별로 저장(recoveryDrafts)
POST /api/adaptive/review     초안에 대한 결정 → 승인한 strategy 또는 거절을 실행 기록의 recoveryAction에 기록
```

- **임시 실행 기록 어댑터**: 그래프를 독립적으로 시험하려고 B의 `ExecutionRecord` 제안 필드 일부를 로컬에 저장한다. B의 최종 스키마나 API를 확정하는 구현은 아니다. 작업이 축소로 교체돼도 테스트 기록이 남도록 `planId`, `taskTitle`을 함께 복사한다.
  - 같은 작업의 미완료 체크인을 결정 전에 다시 보내면(예: 복구 방법을 고르라는 질문에 답할 때) 기록을 새로 만들지 않고 기존 기록을 고친다.
- **초안은 작업마다 하나**다. 같은 작업에 새 체크인이 오면 이전 초안은 항상 사라지거나 새 초안으로 바뀐다.
- **새 계획을 확정하면** 승인 대기 초안은 모두 닫히고, 그 체크인 기록의 `recoveryAction`은 `plan_replaced`가 된다.
- **승인할 때는 복구 방법을 바꿀 수 없다.** 기록되는 strategy가 실제로 적용한 초안과 같아야 하기 때문이다. 다른 방법은 수정(revise)으로 요청한다.
- **계획을 만든 뒤 프로필이 바뀌면** 복구(미완료 체크인·승인·수정)는 막고 계획을 다시 만들라고 안내한다. 완료 체크인과 거절은 그대로 된다.

## 그래프 흐름

```text
recovery (실행 결과)
  → 입력 검증 → 이유 코드로 strategy 결정
  → shrink: 더 나눌 수 있는지 먼저 확인 (이미 줄인 작업, 남은 작업이 최소 시간 미만, 넣을 빈 시간이 없으면 재배치·재계획 선택 요청)
  → 생성 → 코드가 가장 이른 빈 시간에 배치 → 검증 → 실패 시 재생성 (최대 max_retries) → 승인 대기
  → reschedule: 남은 작업을 가장 이른 빈 시간부터 채움 (코드)
       ├─ 다 들어감            → 재배치안 (빈 시간이 x-1분이면 x-1분 + 나머지는 다음 빈 시간)
       ├─ 넘침, 마감이 계획 밖  → 들어간 만큼 배치 + 나머지는 다음 계획으로 이월
       ├─ 넘침, 마감이 계획 안  → AI가 마감 전 빈 시간에 맞게 범위를 줄임(fit_deadline) → 코드가 배치 → 검증
       └─ 마감 전 빈 시간 없음  → 재계획 선택 요청
review (승인 대기 중인 초안에 대한 사용자 결정)
  ├─ approve → 초안 재검증 → PlanWriter로 저장 (revision이 바뀌었으면 저장 안 함)
  ├─ reject  → 기존 계획 유지
  └─ revise  → 이전 초안 + 피드백으로 재생성 (최대 max_revisions)
               실패하거나 한도를 넘으면 기존 초안을 그대로 승인 대기로 둠
```

- **라우팅과 루프는 규칙 기반이다.** LLM(생성기)은 초안 내용만 쓰고, 그 결과는 항상 코드로 검증한다.
  - 축소안의 총 시간은 남은 작업(`remainingMinutes`, 없으면 원래 작업)보다 짧아야 한다. 수정안이 이전 초안과 같으면 실패로 보고 다시 생성한다. (실제 LLM 테스트에서 둘 다 발생했다.)
  - 대체할 작업 id는 LLM이 아니라 코드가 채운다.
  - 축소로 생긴 작업은 다시 축소하지 않는다(`max_shrink_depth=1`). 줄이고 또 줄이면 5분짜리만 남기 때문이다.
  - API 키·한도 오류는 재시도하지 않는다.
  - 시간 배치는 항상 코드가 한다. 축소안도 원래 칸이 아니라 지금 이후의 빈 시간에 넣는다(체크인할 때는 원래 칸이 대개 이미 지났다). AI는 "무엇을 남기고 무엇을 뺄지"만 정하고, 뺀 범위는 `dropped_scope`로 사용자에게 보여준다.
  - 빈 시간 = 가용 시간 − 캘린더 일정 − 계획의 모든 작업(원래 자리 포함) − 다른 작업의 승인 대기 초안. 계획의 여유분(buffer)은 이런 복구에 쓰라고 남겨둔 시간이라 사용한다.
  - 승인할 때 빈 시간을 다시 계산해서, 그사이 지나간 시각이나 다른 일정과 겹치면 저장하지 않는다.
- **그래프는 요청 사이에 상태를 들고 있지 않는다.** 승인 대기 초안과 `revision_count`는 호출하는 쪽이 저장했다가 다시 넘긴다. 그래서 저장소가 로컬 DB에서 공용 DB로 바뀌어도 그래프는 그대로다.
- **저장은 `PlanWriter` 인터페이스로만 한다.** 지금은 로컬 `ExecutionStore` 어댑터, 나중에는 공용 DB 어댑터가 같은 메서드를 구현한다.
- **시스템 제한값은 한 곳에서 정한다.** `max_retries=2`, `max_revisions=2`, `min_task_minutes=5`, `max_shrink_depth=1`은 `build_adaptive_planner_graph` 인자다. 사용자 특성값(집중 시간 등)은 기본값을 넣지 않고 물어본다.

## PlannerState

PlannerState는 DB가 아니라 **그래프 한 번 실행하는 동안의 상태**다. 코드에서는 snake_case를 쓰고, API로 나갈 때 camelCase로 바꾼다.

```text
입력 (호출하는 쪽이 채움)
  request            new_plan | recovery | review
  user_id, project_id
  planning_context   A의 get_planning_context(user, project) 결과. 그래프는 읽기만 함
  execution_context  그래프가 판단에 쓰는 값만 뽑은 것 (schedule_style, focus_minutes 등)
  current_task       복구 대상 작업 (recovery일 때 필수)
  schedule_context   now, 빈 시간, 마감 (shrink·reschedule·승인에 필수). 시각은 시간대 없는 현지 시각
  check_in           B의 ExecutionRecord에서 변환 (recovery일 때 필수)
  base_revision      초안을 만들 때 기준이 된 계획 revision
  strategy           사용자가 직접 고른 복구 방법 (없으면 reason_code로 결정)
  decision           review일 때: approve | reject | revise
  pending_draft      review일 때: 사용자가 보고 있는 초안 (클라이언트가 아니라 저장소에서 읽음)
  user_feedback      revise일 때: 수정 요청 내용 (생성기에 데이터로만 전달)
  revision_count     revise일 때: 지금까지 수정한 횟수 (초안과 함께 저장)
진행 (그래프가 채움)
  route              new_plan | recovery | review | continue | request_information
  strategy           shrink | reschedule | replan
  draft, validation_errors, retry_count, retry_limit
결과
  approval_status    not_required | needs_input | waiting | approved | rejected | fallback
  fallback, error
  profile_update_proposal   B의 ProfileUpdateProposal. 그래프는 제안만 하고 프로필을 바꾸지 않음
```

- **새 계획(new_plan)은 사용자 컨텍스트가 있어야 만든다.** `planning_context`가 없으면 일반 계획을 만들지 않고 입력을 요청한다.
- **사용자가 복구 방법을 직접 고를 수 있다.** 예를 들어 채팅에서 "줄여줘"라고 하면 `strategy = shrink`가 된다.

## 계획 스타일 (schedule_style)

사용자마다 계획을 짜는 방식이 다르므로 시간 단위로만 접근하지 않는다. 기준값은 UserProfile에 둔다 (A 담당, 필드 요청함). 지금은 기존 필드 `planningPreferences.scheduleStyle`을 읽는데, 이 값은 설문에서 직접 묻지 않고 생활 규칙성으로 추정된 값이다. PlannerState는 이 값을 `execution_context.schedule_style`로 복사해 읽기만 하므로, A가 필드 이름을 바꿔도 converter만 고치면 된다.

| | time_blocks (깐깐형) | flexible_queue (덩어리형) |
|---|---|---|
| 예시 | 6시 반까지 A, 7시까지 B | 저녁에 A 1시간, B 2시간 |
| 계획 생성 | 작업을 집중 시간 이하로 나눔 | 결과물 단위로 묶음 (가용 시간 덩어리까지) |
| 축소 검증 | 작업마다 집중 시간 이하 | 집중 시간은 검사하지 않음. 범위 축소는 프롬프트가 담당 |
| 집중 시간 | 필수 | 없어도 됨 |

프롬프트는 하나만 두고, 타입별 지시 블록(`execution_api.SCHEDULE_STYLE_INSTRUCTIONS`)을 끝에 붙인다.
스케줄러는 아직 두 타입 모두 시각을 배치한다. 덩어리형 배치 모드는 따로 진행한다.

## reasonCode → strategy

B의 이유 코드 8개를 그대로 쓴다.

| reasonCode | strategy |
|---|---|
| task_too_large, unclear_task, fatigue | shrink |
| time_shortage, interruption, underestimated | reschedule |
| priority_changed | replan |
| other | 사용자에게 복구 방법 선택 요청 |

## 다른 팀 데이터 계약과의 연결

**A → 그래프**
- `get_planning_context(user, project)` → `planning_context`
- `planningPreferences.scheduleStyle` → `schedule_style`
- `planningPreferences.blockMinutes` → `focus_minutes`
  - 사용자가 집중 시간을 "모름"으로 답했으면 `None`. blockMinutes에 들어 있는 기본값(15분)을 가져오지 않는다.

**B → 그래프**
- `result` → `completed`
- `actualMinutes` → `actual_minutes`
- `reasonCode` → `reason_code`
- `note` → `note`

**그래프 → B**
- 승인된 `strategy`를 `ExecutionRecord.recoveryAction`에 기록한다.

## 프로젝트별 채팅방

프로젝트마다 채팅방을 두고, 각 방의 AI는 `UserProfile(공통) + 해당 프로젝트 정보`를 읽는다. 호출할 때 `project_id`와 `planning_context`만 바꾸면 된다.

- **가용 시간과 캘린더는 모든 방이 공유한다.** 그래야 A 방과 B 방이 같은 시간에 작업을 넣지 않는다.
- **채팅 내용이 UserProfile을 직접 바꾸지 않는다.** 프로필은 `ProfileUpdateProposal` → 사용자 승인을 거쳐서만 바뀐다.

## 직접 테스트하기

> 이 브랜치는 로컬 실행 상태에 새 필드를 추가한다. 기존 테스트 데이터를 유지할 필요가 없으면 서버를 끄고 기본 경로 `data/replan.sqlite3`를 삭제한 뒤 실행한다. `REPLAN_DB_PATH`를 설정했다면 그 경로의 파일을 사용한다.

1. 의존성 설치 후 앱 실행: `pip install -r requirements.txt` → `python run_local.py`
2. 앱 화면에서 실행 프로필 → 가용 시간 → 주간 계획 생성·확정
3. `http://127.0.0.1:8010/docs` 열기
   - `GET /api/execution`: `revision`과 `plan.entries`의 작업 `id` 확인
   - `POST /api/adaptive/check-in`: `{"revision", "taskId", "checkIn": {"completed": false, "reasonCode": "task_too_large", "actualMinutes": 10, "note": "..."}, "consent": true}` (완료면 `"completed": true`)
     - 재배치는 `reasonCode`를 `time_shortage`·`interruption`·`underestimated`로. 남은 작업 시간은 `remainingMinutes`(없으면 작업 전체), 캘린더 일정은 `events`(`/api/execution/plan`과 같은 형식)
   - 응답의 `result.draft`가 AI 축소안, `recoveryDraft.id`가 검토할 초안 id. 기록은 `GET /api/execution`의 `executionRecords`
   - `POST /api/adaptive/review`: `{"revision", "draftId", "decision": "revise", "feedback": "...", "consent": true}` 또는 `"approve"` / `"reject"`
4. 승인하면 앱의 주간 계획 화면을 새로고침해 바뀐 작업 확인

## 원칙

- 검증을 통과하지 않은 안은 승인 대기로 넘어가지 않는다. 승인 전에는 계획과 프로필이 바뀌지 않는다.
- 필요한 값이 없으면 기본값을 넣지 않고 사용자에게 입력을 요청한다. 예를 들어 집중 시간이 없다고 20분으로 가정하지 않는다.
- 재시도·수정 횟수는 0~5회로 제한하고, 한도를 넘으면 기존 계획(또는 기존 초안)을 유지한다.
- 승인할 때도 초안을 다시 검증한다. 검증을 통과하지 못한 초안은 저장소에 닿지 않는다.
- 생성기·저장소 오류의 원문은 저장하지 않고 오류 코드만 남긴다.
