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
- id, profileId, taskTitle, plannedMinutes, createdAt은 서버가 저장.
- 직접 records API는 동일 작업 중복을 차단한다. C의 대화 후속 입력은 복구 미결정 기록을 보완하고, 결정 후 재시도는 새 기록을 만든다. 후보 근거로 사용한 기록은 수정하지 않는다.
- 완료 체크박스는 현재 계획 상태만 변경하며 과거 체크인 결과는 유지한다.

POST /api/execution/proposals/{id}/approve 또는 /reject
- 요청: revision
- 승인 시 프로필 변경과 결정 기록을 같은 트랜잭션으로 저장.
- 프로필 교체·수정 중, 중복 처리, 오래된 revision은 충돌 처리.
- 승인 시 새 프로필 ID를 부여하고 기존 계획 초안을 무효화.
  확정된 계획은 유지한다.
- 확정 계획이 있으면 화면은 명시적 LLM 전송 동의를 받은 뒤 승인 응답의 새
  revision으로 `/api/execution/plan`을 호출한다. 이때 `profileChangeProposalId`를
  전달하고, C converter가 변경 전후·이유·근거를 `profile_change_context`로 바꾼다.
- 재계획 결과는 기존 `planDraft` 검토 화면에만 저장된다. 사용자가
  `/plan/confirm`을 호출하기 전에는 기존 확정 계획을 바꾸지 않는다.

## 첫 규칙: long-task-v1

현재 프로필로 생성한 작업 중 최근 14일의 50분 이상 작업 마지막 3건이
모두 미완료이고 2건 이상이 시간 부족 또는 작업 크기를 이유로 기록되면
blockMinutes를 20분으로 줄이는 후보를 만든다. 현재 값이 20 이하이면
생성하지 않는다. 같은 프로필에 대기 후보가 있거나 기존 후보와 근거가
겹치면 생성하지 않는다. 승인·거절 여부와 무관하게 근거 중복을 막는다.
거절 후 서로 다른 새 근거 3건이 쌓이면 다시 제안할 수 있다.

후보에는 변경 전후 값, 이유, 근거 ID, 규칙 버전, 생성·결정 시각을 보존한다.
실제 시간과 예정 시간 차이는 화면에서 표시하며, 그 자체를 실패로 판단하지 않는다.
전체 초기화는 실행 기록과 후보도 삭제한다.

## 검증

.venv/bin/python -m unittest discover -s server/tests
npm test
npm run build

## C의 실행 요약 연결

GET /api/execution/summary?days=14&planId=...&profileId=...

세 쿼리는 모두 선택값이다. days는 1~365, 기본 14일이다.
planId와 profileId를 생략하면 해당 기간의 전체 기록을 집계한다.
집계 기간은 체크인 createdAt 기준이며 미래 기록은 제외한다.
응답은 전체 상태가 아닌 ExecutionSummary 객체이므로 기존 executionApi
프론트 함수 대신 별도 조회를 사용해야 한다.

- revision: 집계한 저장 상태의 revision
- periodStart, periodEnd: 집계 범위의 UTC 시각 (양 끝 포함)
- days, planId, profileId: 적용한 필터
- recordCount: 기록 개수
- resultCounts: completed, partial, not_started, incomplete 각각의 개수
- completionRate: 기록 중 completed 비율, 0~100%, 소수 둘째 자리 반올림
- plannedMinutes: 전체 기록의 예정 시간 합계
- actualMinutes: 실제 시간이 입력된 기록의 시간 합계
- minutesDifference: 실제 시간이 입력된 기록에 한해 실제 시간에서 예정 시간을 뺀 합계
- actualMinutesRecordCount: 실제 시간이 입력된 기록 수
- incompleteReasonCounts: 미완료 기록의 이유별 개수 (완료된 지연 작업은 제외)
- evidenceRecordIds: 집계에 사용한 전체 기록 ID, 생성 시각 순

기록이 없으면 완료율은 null, 개수와 합계는 0, 근거 ID는 빈 배열이다.
미기록 작업은 분모에 포함하지 않는다. 이 요약은 관찰 결과이며 승인된
개인화 선호가 아니다. C는 이 요약만으로 프로필을 자동 변경하면 안 된다.
승인 후 이전 프로필의 기록도 필요하면 profileId 필터를 생략한다.

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
