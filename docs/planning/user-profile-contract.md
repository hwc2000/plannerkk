# A 담당: 사용자 프로필·대화·계획 컨텍스트

최종 갱신: 2026-10-06. 이 문서는 현재 로컬 구현을 기준으로 한다.

기준: `adaptive-planner-state-contract.md`, PR #8 (head `c4c2a84`).
API/DB는 camelCase, C의 그래프 내부는 snake_case를 유지한다.
PR #8은 참조만 했으며 B의 기능 전체를 이 작업에 병합하지 않았다.

## 스키마

검증 가능한 정의: `server/app/user_profile.py` (`SurveyAnswers`, `PlanningPreferences`, `LearnedPattern`, `UserProfile`).
프론트엔드 계약: `src/shared/types.ts`. JSON Schema: `user-profile.schema.json`.

| UserProfile 필드 | 의미 |
|---|---|
| id | 해당 확정본 식별자. B/C의 기존 profileId 비교와 호환되도록 변경 승인 시 새 ID |
| userId | 서버 저장소가 결정한 사용자 ID |
| schemaVersion | 구조 버전 2.0 |
| version | 프로필 확정/변경 승인마다 증가. 전체 상태 revision과 별개 |
| declaredFacts | 명시적으로 응답한 설문/대화 정보 |
| facts | 기존 UI/B/C 호환용 declaredFacts의 동일한 사본. 새 소비자는 declaredFacts 사용 |
| planningPreferences | 대화에서 정리한 응답으로 계산하고 사용자가 확정한 계획 선호 |
| learnedPatterns | 승인된 관찰, 근거 executionRecord ID, proposal ID, 적용 범위, 만료/철회 상태 |
| surveyResponseId | 원본 설문 연결. 원본이 없는 기존 데이터는 null |
| insights | 기존 요약/전략/후속 질문 구조. LLM의 원문 설명은 컨텍스트에 자동 포함하지 않음 |
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

## 대화형 프로필 생성

기존 4단계 설문 화면을 제거하고 챗봇으로 통일했다. 대화 → 프로필 요약 검토 → 확정 순서다.
기존 프로필 수정도 대화로 진행한다. API 키가 있으면 AI 자유 대화를 기본 선택하되 전송 동의를 받는다.

- 안내형: 서버 질문/선택지 및 분/시간 입력을 파싱. API 키 불필요.
- AI 자유 대화: 대화 전송 동의 후 LLM이 명시된 답변만 추출.
- 추출한 필드마다 사용자 메시지 ID와 인용 근거를 검증/저장. AI 발언을 사실 근거로 사용하지 않음.
- 대화는 `profileConversations`에 저장되어 새로고침 후 이어갈 수 있음.
- 질문이 끝나면 profileDraft 생성 → 대화 요약 검토/대화로 수정 → 프로필 확정.
- 기존 확정 프로필은 새 초안을 확정하기 전까지 유지됨.
- AI 의미 해석은 완벽하지 않으므로 최종 검토가 필수. 원문 근거 검증은 의미적 정확성의 증명이 아님.
- 원본 설문 `surveyResponses`와 계산된 선호를 분리. 대화에서 생성한 설문에는 conversationId/extractionEvidence 포함.

### 대화 응답 계약과 흐름

`profile_conversation`의 LLM 응답은 다음 구조다. 프로필 추출과 실제 대화 답변을 한 번의 요청에서 생성한다.

```ts
type ConversationReply = {
  reply: string
  nextField: keyof SurveyAnswers | null
  updates: Array<{
    field: keyof SurveyAnswers
    value: string | string[] | number | null
    messageId: string
    quote: string
  }>
}
```

위 타입은 개요다. 실제 `EXTRACT_SCHEMA`는 필드별 `anyOf`로 값의 타입과 열거값을 제한한다.
예를 들어 roles/barriers는 배열, focusMinutes/dailyMinutes는 정수 또는 null이다.

- `reply`: 사용자가 읽을 전체 답변과 후속 질문. AI 모드에서는 서버가 고정 질문을 덧붙이지 않는다. 검증을 통과한 LLM 답변을 그대로 저장한다.
- `nextField`: 새 답변에서 실제로 묻는 항목. 이 값에 맞는 선택지나 고정 일정 선택기를 표시한다. 단순히 직전 질문을 반복하는 값이 아니다.
- `nextField=null`: 선택지 없이 자유롭게 설명할 차례이거나 질문이 끝난 상태. 이것만으로 프로필이 완성된 것으로 처리하지 않는다.
- `updates`: 이번에 명시적으로 새로 말하거나 수정한 정보만 포함한다. `messageId`는 사용자 메시지여야 하고 `quote`는 그 메시지에 실제 포함된 비어 있지 않은 문자열이어야 한다.
- `/chat` 조회의 `ready`: 다음 질문이 없고 모든 응답 항목이 채워졌을 때만 true다. `unknown`, 시간의 null, 추가 설명의 빈 문자열도 명시적 응답으로 인정한다.
- 안내형에서는 서버 질문 순서와 파서를 사용한다. AI가 없는 경우의 대안이며 AI 응답으로 가장하지 않는다.
- 수정할 항목을 선택하면 `pendingField`를 설정한다. AI 응답 후에는 모델의 `nextField`로 질문 흐름을 이어간다.

대화 저장에는 `id`, `userId`, `status(active/reviewed)`, `answers`, `evidence`, `messages`, `createdAt`과
선택적인 `pendingField`/`nextField`를 사용한다. 메시지는 `id`, `role`, `content`, `createdAt`을 가진다.
`/chat` 조회 시에는 `question`, `ready`, `editableQuestions`를 계산해서 추가한다.
기존 진행 중 대화는 이어서 사용하고, 새 수정 대화는 현재 초안 또는 확정 프로필의 답변을 불러온다.

### 질문의 의미와 말투

예의를 지키는 부드러운 반말을 일관되게 쓰되 질문의 명확성을 우선한다. 존댓말과 반말을 섞지 않는다. 한 번에 필요한 질문 하나를 하고,
현재 습관을 묻는 질문을 앞으로의 희망이나 선호로 바꾸지 않는다.
무례한 명령·비꼼·과도한 친밀감, 반복적인 공감, 추측성 위로, 내부 필드명, ‘회복 선호’, ‘확인하겠습니다’ 같은 표현은 프롬프트에서 피하도록 지시한다.

| 항목 | 묻는 내용과 예시 |
|---|---|
| roles | 현재 학생인지, 일을 하는지 등 생활 형태. 원하는 일정의 종류가 아님 |
| regularity | 현재 생활 시간표의 규칙성. ‘평소 일어나고, 공부하고, 쉬는 시간이 매일 비슷한 편이야, 아니면 날마다 달라져?’ |
| barriers | 최근 계획을 실천하기 어려웠던 이유 |
| focusMinutes | 쉬기 전 **한 번에 연속해서** 집중할 수 있는 시간. 예: 한 번에 25분 |
| dailyMinutes | 필수 일정을 제외한 **하루 전체의 총 가용 시간**. 예: 하루 총 2시간 |
| energy | 집중이 잘되는 시간대. 집중 시간의 길이와 구분 |
| recovery | 계획이 틀어졌을 때 실제로 어떻게 대응하는지 |
| scheduleStyle | 몇 시에 할지 정하는 계획과 작업별 소요량만 정하는 계획 중 선호 |
| constraints | 매주 반복되는 고정 일정의 요일·시간 |
| context | 앞선 답변 외에 고려할 추가 상황. 없음도 가능 |

‘밀린 일을 다시 시작한다’는 말만으로 recovery=replan으로 분류하지 않도록 지시한다.
시간을 다시 잡는지, 할 일을 줄이는지 등 의미가 불분명하면 확인 질문을 한다.
이 의미 구분은 LLM 지침이며 모든 잘못된 추론을 코드로 판별하는 기능은 아니다.

`reply_problem()`/`checked_reply()`는 다음을 검사한다.

1. 답변이 비어 있지 않고 1500자 이내인지 확인한다.
2. 문자 범주의 외국어 글자(영문·한자·일본어 등)를 차단한다. 한글, 숫자, 문장부호는 허용한다. 이 검사는 사용자 원문이나 내부 JSON 열거값이 아닌 사용자에게 보여줄 `reply`에 적용한다.
3. 집중 시간/하루 가용 시간 표현과 생활 규칙성 질문의 혼동, 일부 존댓말 어미(요, 습니다, 세요 등)를 검사한다. 모든 문장의 의미나 말투를 완전히 검증하는 것은 아니다.
4. 실패하면 별도 `profile_reply_rewrite` 요청으로 **한 번만** 재작성한다. 추출 값이나 근거를 재작성 결과로 바꾸지 않는다.
5. 재검증도 실패하면 한국어 오류를 반환하고 해당 턴의 DB 변경을 저장하지 않는다. 기존 대화는 유지된다.

### 중복 질문 방지

프롬프트뿐 아니라 이번 `updates`를 적용한 누적 `answers`로 다음 질문을 검사한다.

- 이미 키가 존재하는 항목은 `unknown`, `null`, 빈 문자열도 답한 것으로 취급한다.
- 모델의 `nextField`가 이미 답한 항목이면 아직 답하지 않은 첫 항목을 다음 질문 대상으로 정한다.
- 사용자가 `/chat/question`으로 직접 고른 `pendingField`이고 이번 턴에서 아직 답변을 추출하지 못한 경우에는 확인 질문을 허용한다.
- 모델 답변이 저장된 이전 챗봇 답변과 앞뒤 공백을 제외하고 완전히 같을 때도 중복으로 처리한다.
- 중복이면 `profile_reply_rewrite`에서 새 질문을 만들게 한다. 모든 항목이 채워졌으면 추가 질문 없이 요약 검토를 안내한다.
- 이 처리로 변경한 `nextField`를 함께 저장하여 화면 선택지와 다음 질문 대상을 맞춘다. 이미 저장된 답을 삭제하거나 다시 입력받는 방식은 아니다.
- 재작성은 기존 한국어·말투 검증과 같은 호출 경로를 사용한다. 다른 표현으로 같은 뜻을 반복하는 모든 문장까지 완벽히 탐지하는 기능은 아니다.

### 선택지와 고정 일정 입력

선택지 버튼은 즉시 전송하지 않는다. 고른 뒤 **‘선택한 답변 보내기’**를 눌러 전송한다.

- roles/barriers는 복수 선택, 나머지는 단일 선택이다. 같은 버튼을 다시 누르면 선택이 해제된다.
- barriers의 none/unknown은 다른 항목과 함께 선택할 수 없다.
- 전송 실패 시 선택을 유지하며, 성공하거나 질문 항목이 바뀌면 선택을 비운다.
- AI 모드에서는 전송 동의가 있어야 답변을 보낼 수 있다.

`nextField=constraints`이면 `FixedSchedulePicker`를 표시한다.
요일 복수 선택, 평일/주말 일괄 선택, 30분 단위 시작·종료 시간 선택, 일정 추가·삭제를 지원한다.
종료 시간에는 24:00도 허용한다. 자정을 넘는 일정은 나누어 입력한다.
같은 요일의 겹치는 일정과 시작보다 이른/같은 종료 시각을 거절한다.
여러 일정을 모아 **‘고정 일정 보내기’**로 전송하거나 **‘고정 일정 없음’**을 선택한다.

현재 선택기 값은 `월요일·화요일 09:00~18:00; 토요일 18:30~19:00` 같은 문장으로 조립해
일반 대화의 `text`로 전송하고 `answers.constraints`에 반영한다.
**별도 반복 일정 테이블에 저장하거나 캘린더/가용 시간에 자동 등록하는 기능은 아직 없다.**
계획에서 시간을 실제로 차단하려면 기존 가용 시간표/캘린더를 사용해야 한다.

### 응답 시간 관리

- 매 턴 전체 대화 대신 최근 저장 메시지 12개와 이번 메시지를 LLM에 보낸다.
- 누적 `answers`, 미응답 항목, 항목별 정의는 함께 전달한다. DB의 전체 대화 기록은 삭제하지 않는다.
- 대화 출력 한도는 1800토큰, 답변 재작성은 500토큰이다. 기존 계획 생성은 6500토큰을 유지한다.
- 대화·재작성 요청은 각각 25초 타임아웃, 기존 계획 요청은 60초이며 SDK 자동 재시도는 0회다.
- 답변 검증 실패 시 재작성 요청이 추가되므로 전체 턴이 25초 안에 끝난다는 보장은 없다. 현재 응답은 스트리밍하지 않는다.
- 저장 메시지 수가 100개 이상이면 새 답변을 거절한다. 일반적인 한 턴은 사용자/응답 메시지 두 개를 추가한다.
- 구체적인 응답 시간은 모델과 네트워크 상황에 따라 달라진다.

### 프로필 초기화

화면의 **‘프로필 초기화하기’** 버튼은 확인창 이후 `/api/execution/profile/reset`을 호출한다.

| 처리 | 대상 |
|---|---|
| null로 초기화 | profile, profileDraft, planDraft |
| 빈 배열로 초기화 | profileConversations, surveyResponses, profileRevisions, profileUpdateProposals |
| 유지 | settings(가용 시간·표시 방식), plan(확정 계획), executionRecords, recoveryDrafts, memories |

서버는 revision을 검사하고 한 트랜잭션으로 처리한다. 성공하면 화면의 대화 입력·선택·동의 상태도 새로 시작한다.
보존된 계획은 과거 프로필을 참조할 수 있다. 새 프로필을 만들기 전에는 프로필이 필요한 계획 생성/복구를 사용할 수 없다.
이 기능은 가용 시간과 확정 계획까지 지우는 기존 `/api/execution/reset` 전체 초기화와 다르다.

## API

기존 설문 입력 API는 호환용으로 유지하지만 화면에서는 단계형 설문을 제공하지 않는다.

```text
POST /api/execution/profile                   구조화된 응답 → 초안 (기존 호환용)
POST /api/execution/profile/confirm           프로필 확정
POST /api/execution/profile/reset             {revision} 프로필·대화 초기화
POST /api/execution/reset                     {revision} 실행 상태 전체 초기화
GET  /api/execution/profile                   확정 프로필
GET  /api/execution/survey-responses          원본 설문 이력
GET  /api/execution/profile/revisions         확정본 스냅샷 이력
POST /api/execution/planning-context          계획 요청(WeeklyRequest) → 공통 컨텍스트
GET  /api/execution/profile/chat              진행 중 대화와 다음 질문
POST /api/execution/profile/chat/start        {revision}
POST /api/execution/profile/chat/message      {revision, sessionId, text, mode, consent}
POST /api/execution/profile/chat/question     {revision, sessionId, field} 수정할 항목 선택
POST /api/execution/profile/chat/draft        {revision, sessionId}
```

모든 쓰기는 revision을 검사하고 SQLite 트랜잭션으로 처리한다. 충돌은 409.
프로필 변경은 planDraft만 무효화하며 확정된 과거 계획은 보존한다.
프로필 재작성은 최신 명시 응답으로 새 프로필을 생성하며 기존 패턴은 변경 이력에 보존한다. 프로필 초기화는 이 이력도 삭제한다.

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
프로필의 자유 텍스트 constraints/context와 전체 대화는 기본적으로 계획 LLM에 전송하지 않는다.
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

테스트는 임시 DB와 Fake LLM으로 사용자 분리, 원본 재조회, 승인 격리,
버전 충돌, PR #8 제안 적용, 기억 필터, 레거시 보존, 대화 근거 검증,
대화 기본 진입/요약 검토/대화 수정, 모델의 후속 질문 연결, 미완성 프로필 차단,
한국어 답변 재작성/실패 처리, 집중·가용 시간 구분, 생활 규칙성 질문의 명확성,
복수 선택과 제외 항목, 고정 일정 선택/중복 검증, 초기화 확인과 데이터 보존을 검증한다.

2026-10-06 기준 마지막 실행 결과: 백엔드 145개, 프론트엔드 24개 통과.
프론트엔드 타입 검사와 프로덕션 빌드도 통과했다. 이번 중복 질문·말투 수정과 함께 백엔드 검증을 실행했다. 프론트엔드 결과는 직전 실행 기준이다.

## 주요 구현 파일

- `server/app/user_profile.py`: A 프로필 검증, 버전 이력, B 승인 적용 경계
- `server/app/profile_chat.py`: 대화 저장, 추출 근거 검증, 후속 질문, 답변 검증·재작성
- `server/app/planning_context.py`: A 공통 Context Loader와 정보 필터링
- `server/app/execution_store.py`: 사용자별 저장 및 레거시 호환
- `server/app/execution_api.py`: 프로필/조회/초기화/계획 API
- `server/app/execution_llm.py`: 모델 호출과 출력량·타임아웃
- `src/features/execution/ProfileChat.tsx`: 대화 화면·선택지·복수 선택
- `src/features/execution/FixedSchedulePicker.tsx`: 고정 일정 선택기
- `src/features/execution/ExecutionView.tsx`: 프로필 요약·확정·초기화
- `src/features/execution/profileLabels.ts`: 사용자 표시용 항목 이름

기존 `ProfileForm.tsx`는 제거했다. 현재 화면 진입은 챗봇으로 통일되어 있다.
