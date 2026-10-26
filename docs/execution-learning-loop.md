# 실행 결과와 개인화 학습 루프

스키마만 확인하려면 [B 담당 스키마](execution-schema.md)를 참고하세요.

기본 로컬 사용자는 SQLite execution_state에 executionRecords와
profileUpdateProposals 배열을 저장한다. A의 ExecutionStore(user_id=...) 저장 경계를
사용하며 기존 DB는 누락 항목을 보완한다. HTTP 인증·사용자 식별 연결은 별도 범위다.

## API

모든 변경 요청에는 최신 revision이 필요하다. 응답은 전체 실행 상태다.
조회: GET /api/execution (실행 기록과 후보 포함).

POST /api/execution/records
- planId, taskId: 현재 확정 계획의 작업
- actualMinutes: 정수 0~1440 또는 null (미입력)
- remainingMinutes: 정수 0~1440 또는 null. 사용자가 추정한 남은 작업량이며 시간 차이로 자동 계산하지 않는다.
- result: completed / partial / not_started / incomplete
- reasonCode: time_shortage / task_too_large / fatigue / interruption /
  priority_changed / unclear_task / underestimated / other
- note: 최대 2000자, difficulty: 선택값 1~5, recoveryAction: 최대 1000자
- partial/not_started는 reasonCode 필수. incomplete는 상세 결과·이유를 아직 모르는 미완료 상태다. 미시작은 실제 시간 0분만 허용. 완료는 남은 시간 0 또는 null만 허용.
- id, profileId, profileVersion, projectId, projectProfileId, taskTitle, plannedMinutes, createdAt은 서버가 저장. profileVersion·projectId·projectProfileId는 계획에서 복사하며, 계획이 바뀐 뒤에도 프로젝트·프로필 버전별로 기록을 모을 수 있게 한다.
- 직접 records API는 동일 작업 중복을 차단한다. C의 대화 후속 입력은 복구 미결정 기록을 보완하고, 결정 후 재시도는 새 기록을 만든다. 후보 근거로 사용한 기록은 수정하지 않는다.

POST /api/execution/task (완료 체크박스)
- 체크하면 completed 실행 기록을 하나 만든다(실제 시간 미입력). 체크로 끝낸 작업도 완료율·학습에 들어간다.
- 체크를 풀면 그 작업의 마지막 기록이 completed일 때 그 기록만 지운다. 이전 미완료·부분 완료 기록은 유지한다. 후보 근거로 쓴 기록이면 충돌로 거절한다.
- 이미 같은 상태면 아무것도 바꾸지 않는다.

POST /api/execution/proposals/{id}/approve 또는 /reject
- 요청: revision
- 승인 시 프로필 변경과 결정 기록을 같은 트랜잭션으로 저장.
- `projectId`가 있는 후보는 그 프로젝트 설정만 바꾼다(사용자 프로필 ID·버전 유지). 계획 초안은 같은 프로젝트 것만 무효화한다.
  지금 확정 계획이 다른 프로젝트면 재계획하지 않고, 그 프로젝트의 다음 계획부터 반영된다.
- 프로필 교체·수정 중, 중복 처리, 오래된 revision은 충돌 처리.
- 승인 시 새 프로필 ID를 부여하고 기존 계획 초안을 무효화.
  확정된 계획은 유지한다.
- 확정 계획이 있으면 화면은 명시적 LLM 전송 동의를 받은 뒤 승인 응답의 새
  revision으로 `/api/execution/plan`을 호출한다. 이때 `profileChangeProposalId`를
  전달하고, C converter가 변경 전후·이유·근거를 `profile_change_context`로 바꾼다.
- 재계획 결과는 기존 `planDraft` 검토 화면에만 저장된다. 사용자가
  `/plan/confirm`을 호출하기 전에는 기존 확정 계획을 바꾸지 않는다.

## 첫 규칙: long-task-v2 (v1: 50분 이상 작업 → 20분 고정)

규칙은 **범위별로** 돈다. 범위는 기록의 프로젝트(`projectId`)이고, 프로젝트 없는 기록은 사용자 범위다.
한 프로젝트에서 찾은 패턴은 그 프로젝트에만 적용하는 후보(`projectId` 포함)가 되어, 어려운 프로젝트
하나가 다른 프로젝트의 계획까지 줄이지 않는다. 범위의 현재 설정(사용자 프로필 버전 + 그 프로젝트 설정
버전)으로 만든 기록만 센다. 대기 후보는 범위마다 하나다. 기준값(현재 집중 구간)은 프로젝트 설정을
덧씌운 적용값이다.

**언제 제안하나 (규칙):** 그 범위의 현재 집중 구간 절반 이상으로 계획한 작업 중 최근 14일의 마지막 3건이
모두 미완료이고 2건 이상이 시간 부족 또는 작업 크기를 이유로 기록되면 후보를 만든다. 고정 분량(50분 같은)은
쓰지 않고 그 사용자·그 프로젝트의 집중 구간을 기준으로 본다.

**얼마나 줄이나 (사용자 기록에서):**
1. 근거 작업에서 실제로 집중한 시간(`actualMinutes` > 0)의 가운데 값을 5분 단위로 내린 값(최소 5분, 현재보다 짧을 때만).
   실제 시간이 없으면 크기를 정할 근거가 없으므로 후보를 만들지 않는다. `sizedBy = "evidence"`, `sizing`에 근거 문장.
2. 사용자가 기록할 때 AI 판단에 동의했으면(`/records`의 `consent`, 체크인은 원래 동의함) 기록 트랜잭션이 끝난 뒤
   LLM이 작업 제목·예정·실제·남은 시간·이유·난이도·메모를 보고 새 길이를 정한다. 현재보다 짧고 5분 이상일 때만
   받아들이고(`sizedBy = "ai"`, `aiReason`), 실패하거나 범위를 벗어나면 1번 값을 그대로 둔다.

같은 범위에 대기 후보가 있거나 기존 후보와 근거가 겹치면 생성하지 않는다. 승인·거절 여부와 무관하게 근거 중복을 막는다.
거절 후 서로 다른 새 근거 3건이 쌓이면 다시 제안할 수 있다.

후보에는 변경 전후 값, 이유, 근거 ID, 규칙 버전, 생성·결정 시각을 보존한다.
실제 시간과 예정 시간 차이는 화면에서 표시하며, 그 자체를 실패로 판단하지 않는다.
전체 초기화는 실행 기록과 후보도 삭제한다.

## 두 번째 규칙: focus-time-v1 (집중이 잘 되는 시간대)

설문은 집중이 잘 되는 시간대를 묻지 않는다(10/15). 대신 기록이 쌓이면 이 규칙이 찾아 **기본 프로필**
`planningPreferences.focusTime` 변경 후보를 만든다. 시간대는 사람의 성향이라 프로젝트 범위가 아니라 사용자 범위다.
승인하면 배치가 그 시간대를 먼저 쓴다(기존 `place_tasks` 규칙, 근거 출처 `learned`).

**언제 제안하나 (규칙):** 현재 프로필로 만든 최근 28일 기록 중 계획 시각(`plannedStart`)이 있는 것을 오전(5~12시)·오후(12~18시)·
저녁(18~24시)으로 나눈다. 4건 이상인 시간대가 **둘 이상**이어야 비교한다. 가용시간이 저녁뿐인 사용자는 저녁 말고는 기록이
없으니 "저녁이 잘 맞는다"고 말할 근거가 없다(가용시간이 무엇을 비교할 수 있는지 정한다). 끝낸 비율이 가장 높은 시간대가 다른
모든 비교 시간대보다 25%p 이상 높고 지금 값과 다르면 후보를 만든다. 대기 중인 시간대 후보가 있으면 만들지 않고,
마지막 시간대 후보(승인·거절 무관) 이후의 기록만 세므로 거절하면 새 근거가 쌓여야 다시 제안한다.

**어느 시간대인가:**
1. 끝낸 비율이 가장 높은 시간대(`sizedBy = "evidence"`, `focusStats`에 시간대별 계획·완료 수).
2. 사용자가 AI 판단에 동의했으면 LLM이 시간대별 수와 작업(시간대, 제목, 결과, 이유, 난이도, 메모)을 함께 보고 정한다.
   비교한 시간대 중 하나일 때만 받아들이고(`sizedBy = "ai"`, `aiReason`), 애매하다고 하거나 범위를 벗어나면 1번 값을 둔다.

두 규칙의 후보는 서로 막지 않는다(대기·근거 중복은 같은 값을 바꾸는 후보끼리만 본다). 승인하면 같은 값을 바꾼 이전 학습
패턴만 superseded가 되고, 다른 값을 배운 패턴(예: 줄인 집중 구간)은 그대로 active다.

## 세 번째 규칙: focus-grow-v1 (집중 구간 늘리기)

1. 언제: 같은 범위(프로젝트별, 또는 프로젝트 없는 작업)의 현재 설정으로 만든 기록 중 집중 구간의 80% 이상인 작업
   마지막 4건이 모두 완료(체크박스 완료도 포함)이고, 같은 범위에 대기 중인 집중 구간 후보가 없을 때.
2. 얼마나: 지금 집중 구간의 5분의 1을 5분 단위로 내림(최소 5분)만큼 늘린다. 50분 → 60분, 30분 → 35분.
3. 상한: 프로필 범위(180분), 하루 계획량이 있으면 그 값, 그리고 이 범위에서 예전에 줄인 적이 있으면 줄이기 전 길이보다
   5분 짧게. 예전에 50분 → 30분으로 줄였다면 늘려도 45분까지만이라 줄이기·늘리기를 오가지 않는다.
4. AI 판단 없음: 늘리는 폭은 고정 단계라 LLM에 보내지 않는다. 승인 뒤 다시 못 끝내면 long-task-v2가 줄이기를 제안한다.

## 프로젝트를 끝낼 때 (project-close-v1)

사용자가 프로젝트 대화에서 ‘프로젝트 끝내기’를 누르면 미리보기에서 넘길 값을 보여 주고, 확인하면 바로 기본 프로필에
반영한다(끝내기 자체가 승인). 기록은 `ruleVersion = project-close-v1`, `sourceProjectId`가 있는 승인된 후보로 남는다.
설계와 표는 `server/app/project_close.py` 맨 위.

- 넘기는 것: 그 프로젝트에서 기록으로 배운 집중 구간(그 길이 작업 3건 이상, 3분의 2 이상 완료), 그 프로젝트에서 승인한
  복구안이 3건 이상이고 3분의 2 이상이 같은 방식이면 ‘계획이 틀어졌을 때’(줄이기 → reduce, 옮기기 → replan)
- 넘기지 않는 것: 사용자가 그 프로젝트에만 정한 값, 아직 배우는 규칙이 없는 하루 계획량·시작 행동,
  이미 모든 기록으로 배우는 집중이 잘 되는 시간대
- 함께 일어나는 것: 그 프로젝트의 남은 작업·배치 못 한 작업·복구안을 이번 주에서 빼고, 대기 중인 그 프로젝트 후보는 거절,
  대화·계획은 다시 열 때까지 막음. 남은 다른 작업이 새 값과 무관하면 이번 주 계획은 계속 유효(기본 프로필 ID를 옮김)

## 검증

.venv/bin/python -m unittest discover -s server/tests
npm test
npm run build

## 실행 요약을 읽는 곳

예전 `GET /api/execution/summary`는 부르는 곳이 없어 지웠다(10/19). 플래너 대화는 정보 꺼내기 `records`로
최근 14일 이 대화의 실행 기록과 승인 대기 변경을 읽는다(`planner_skills.records_view`).

## Python 서비스 연결

server.app.execution_service.ExecutionService(store)

- record_execution(revision, payload): 검증 후 저장, 패턴 탐지와 후보 생성
- decide_proposal(revision, proposal_id, decision): approve 또는 reject
- get_execution_summary(days=14, plan_id=None, profile_id=None): 읽기 전용 요약

앞의 두 함수는 전체 상태를 반환하고 ExecutionStore.change 트랜잭션을 사용한다.
입력 검증은 서비스에서도 적용되므로 C가 HTTP를 거치지 않고 호출할 수 있다.
ConflictError는 오래된 revision·중복 기록·처리된 후보·프로필 충돌을 뜻한다.
ProposalNotFoundError는 후보가 없다는 뜻이며 HTTP에서는 404로 변환한다.

C가 이미 같은 revision의 상태를 로드했다면
summarize_execution(state, days=14, plan_id=None, profile_id=None)를 사용해
추가 DB 조회 없이 PlannerState.executionSummary를 구성할 수 있다.
사용자 승인 확인은 호출자가 담당하며, GPT의 자의적인 approve 호출로
사용자 승인을 대신해서는 안 된다. 현재 저장소는 단일 사용자 전용이다.

## C 체크인·복구 연결

adaptive/local.py의 record_check_in은 B의 save_execution_record를 호출한다.
C의 completed=false는 부분 실행 여부를 임의 추론하지 않고 incomplete로 저장한다.
actualMinutes와 remainingMinutes는 미입력 시 null을 보존한다.
C의 복구 판단용 기본 남은 시간과 사용자가 실제 입력한 값은 구분한다.

save_execution_record(state, payload, allow_follow_up=False)는 트랜잭션 내부 함수다.
ExecutionService.record_execution은 직접 기록용 트랜잭션 래퍼다.
C는 자신의 store.change 안에서 호출하여 기록과 복구 초안을 원자적으로 저장한다.

set_recovery_action(state, record_id, action)은 같은 트랜잭션 안에서
shrink/reschedule/keep_current_plan/plan_replaced 결정과 recoveryDecidedAt을 저장한다.
C의 close_draft에서 호출하므로 복구안 승인 시 계획 변경과 기록 갱신이 함께 커밋된다.

대기 중인 B 제안 객체는 그래프 입력에 직접 넣지 않는다. 승인된 제안만 C의
`profile_change_context`로 변환해 전체 재계획 근거로 전달한다. 이번 체크인으로
새로 생성된 후보는 adaptive 응답의 profileUpdateProposals에 포함된다.
adaptive 응답은 `/api/execution`과 같은 전체 상태(llmAvailable·model 포함)에
recoveryDraft·result·recordId를 더한 형태다. 화면은 응답을 그대로 상태로 교체한다.
실행 결과 화면에서 이유가 priority_changed이면 `/records` 대신 C의
`/api/adaptive/check-in`(strategy=replan, 명시적 LLM 전송 동의)으로 보내고,
결과 기록(result=incomplete)과 전체 재계획 초안을 함께 저장한다.
프로필 변경 승인과 계획 초안 확정은 별도 사용자 결정이다. 프로필 변경 후에도
기존 계획의 완료 기록과 복구안 거절은 가능하지만, 새 프로필 값으로 기존 계획의
일부만 복구하는 것은 새 계획 확정 전까지 차단한다.

## A 프로필 승인 연동

B의 decide_proposal은 승인 시 동일한 store.change 트랜잭션 안에서
A의 apply_profile_proposal(state, proposal_id, expected_version=profile['version'])을 호출한다.
B에서 planningPreferences를 직접 수정하지 않는다. 거절은 프로필을 유지한다.

A의 함수가 프로필 ID·버전·변경 전 값·근거 기록을 검증하고 다음을 함께 저장한다.

- planningPreferences.blockMinutes 변경과 starterMinutes 상한 보정
- 프로필 ID 갱신 및 version 증가
- 승인된 learnedPatterns와 profileRevisions 스냅샷
- 후보의 approved 상태, decidedAt, appliedProfileId
- 오래된 planDraft 무효화

다음 계획 생성은 A의 get_planning_context를 통해 승인된 선호와 패턴을 읽는다.
C는 A의 get_planning_context로 승인된 프로필을 읽고, 승인된 제안만 converter를 통해
profile_change_context로 변환해 전체 재계획에 전달한다. 설문 원본 declaredFacts는 유지한다.
시간 플래너와 할 일 플래너 모두 blockMinutes를 작업 길이 상한으로 사용한다.
그래서 승인된 집중 구간 변경은 두 방식 모두에서 다음 계획의 작업 길이로 바로 보인다.

검증: 실제 B API를 통한 후보 생성·승인·거절, 승인 전 컨텍스트 제외,
승인 후 버전/근거/이력 저장, C converter와 다음 계획에 변경값 전달,
오래된 후보 및 잘못된 근거 거절과 트랜잭션 롤백을 임시 DB에서 확인했다.

`profileId`는 사용자를 식별하지 않는다. 같은 사용자의 프로필 버전을 구분해
계획과 실행 성과가 어떤 설정에서 만들어졌는지 추적한다. `userId`는 별도 소유자
식별자이고 `projectId`는 계획의 프로젝트 범위다. 현재 SQLite 문서는 단일 로컬
사용자용이므로 실제 다중 사용자 환경에서는 인증에서 얻은 userId 기반 분리가 필요하다.
