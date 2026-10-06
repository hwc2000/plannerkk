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

검증 가능한 정의: `server/app/user_profile.py` (`SurveyAnswers`, `PlanningPreferences`, `LearnedPattern`, `UserProfile`).
프론트엔드 계약: `src/shared/types.ts`. JSON Schema: `user-profile.schema.json`.

| UserProfile 필드 | 의미 |
|---|---|
| id | 해당 확정본 식별자. B/C의 기존 profileId 비교와 호환되도록 변경 승인 시 새 ID |
| userId | 서버 저장소가 결정한 사용자 ID |
| schemaVersion | 구조 버전 2.0 |
| version | 프로필 확정/변경 승인마다 증가. 전체 상태 revision과 별개 |
| declaredFacts | 선택형 설문 응답 및 기존 데이터의 호환 필드 |
| facts | 기존 UI/B/C 호환용 declaredFacts의 동일한 사본. 새 소비자는 declaredFacts 사용 |
| planningPreferences | 설문 응답에서 규칙으로 계산하고 사용자가 확정한 계획 선호 |
| learnedPatterns | 승인된 관찰, 근거 executionRecord ID, proposal ID, 적용 범위, 만료/철회 상태 |
| surveyResponseId | 원본 설문 연결. 원본이 없는 기존 데이터는 null |
| insights | 기존 요약/전략/후속 질문 구조. 설문 응답 기반 요약/전략을 표시하며 컨텍스트에는 자동 포함하지 않음 |
| status | draft / confirmed |
| createdAt, updatedAt, confirmedAt | UTC ISO 8601 |

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
