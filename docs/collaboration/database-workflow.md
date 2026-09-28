# DB 협업 워크플로

## 현재 전제

현재 저장소에는 Supabase 프로젝트, DB 스키마, migration이 없다. 프로젝트·마일스톤·캘린더 일정·기억은 브라우저 `localStorage`에 저장된다.

따라서 지금은 팀원별 SQL을 나중에 합치는 단계가 아니라, 공용 데이터 계약을 먼저 합의하는 단계다.

## 작업 시작 전

```bash
git status
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c <이름>/<작업명>
```

진행 중인 개인 브랜치가 있다면 최신 `main`을 먼저 반영한다.

```bash
git fetch origin
git switch <본인-브랜치>
git rebase origin/main
```

여러 명이 함께 사용하는 브랜치는 이력을 재작성하지 말고 `git merge origin/main`을 사용한다. rebase한 개인 원격 브랜치를 갱신할 때만 `git push --force-with-lease`를 사용한다.

## Supabase 생성 전 규칙

1. 각자 별도 이름의 중복 테이블을 만들지 않는다.
2. `profiles`와 `user_profiles`, `tasks`와 `milestones`, `events`와 `calendar_events`처럼 의미가 겹치면 구현 전에 이름을 합의한다.
3. `docs/architecture/supabase-foundation.md`를 공용 초안으로 사용한다.
4. 외부 Supabase 콘솔에서 실험했다면 PR의 근거로 보지 않고 삭제 가능한 실험으로 취급한다.
5. Supabase가 없는데 README나 PR에서 DB/Auth 완료라고 표시하지 않는다.

## Supabase 생성 후 규칙

1. Git의 `supabase/migrations/*.sql`이 스키마의 유일한 기준이다.
2. 일반 변경은 **migration 작성 → 로컬 빈 DB 적용 → 검토 → 공용 환경 적용** 순서로 진행한다.
3. 대시보드 직접 변경은 장애 대응처럼 불가피한 경우에만 허용하고, 즉시 migration으로 재현한 뒤 schema drift가 없는지 확인한다.
4. `main`에 병합된 migration은 수정·삭제하지 않는다.
5. 스키마 변경은 새 migration 파일로 추가한다.
6. migration 파일명은 충돌하지 않는 UTC timestamp 접두사를 사용한다.
7. 한 PR은 가능한 한 하나의 도메인 변경만 포함한다.
8. 새 테이블·컬럼·enum·RLS 변경은 아키텍처 문서도 함께 갱신한다.
9. 생성된 DB 타입을 사용한다면 schema 변경과 같은 PR에서 갱신한다.

## 스키마 변경 예약

1. 작업 전에 GitHub Issue 또는 팀 합의 문서에 변경할 테이블·컬럼·담당자를 기록한다.
2. 공용 테이블이나 다른 담당자의 FK를 바꾸면 해당 담당자의 확인을 먼저 받는다.
3. 동시에 같은 테이블을 수정하는 작업은 migration 순서와 병합 순서를 합의한다.
4. migration 파일은 생성 직전에 UTC timestamp를 부여하고 PR 전 최신 `main`과 중복 여부를 확인한다.
5. 예약되지 않은 중복 테이블이나 공용 enum 변경은 병합하지 않는다.

## PR 소유권 경계

| 변경 | 주 담당 | 같이 확인할 사람 |
| --- | --- | --- |
| Auth, JWT 검증, 공통 RLS | 기반 담당 | 전원 |
| `user_profiles` | 최민서 | Auth 담당 |
| `projects`, `milestones` | 최현우 | 위험도·AI 담당 |
| `calendar_events` | 최현우 | AI 재조정 담당 |
| `memories` | 최현우 | AI 기억 담당 |
| 달성률·위험도 계산 | 이준현 | 프로젝트 담당 |
| LangGraph 상태와 DB 컨텍스트 | AI 담당 | 각 데이터 담당 |

공용 파일인 `src/App.tsx`, `src/shared/types.ts`, `server/app/main.py`, `.env.example`, `requirements.txt`를 바꿀 때는 충돌 가능성을 PR 설명에 적는다.

## migration PR 체크리스트

- [ ] 최신 `origin/main`에서 시작함
- [ ] 기존 테이블과 의미가 중복되지 않음
- [ ] 테이블·컬럼 이름과 책임자가 문서에 기록됨
- [ ] PK, FK, `NOT NULL`, `CHECK` 제약을 검토함
- [ ] 삭제 시 `CASCADE`, `SET NULL`, `RESTRICT` 동작을 명시함
- [ ] 사용자 소유 데이터에 `user_id`와 RLS가 있음
- [ ] RLS가 작업별 `USING`과 `WITH CHECK`를 올바르게 구분함
- [ ] 일반 사용자 CRUD는 사용자 JWT 컨텍스트를 사용하며 `service_role`의 RLS 우회에 의존하지 않음
- [ ] 본인 소유 행의 `SELECT`, `INSERT`, `UPDATE`, `DELETE`가 모두 성공함
- [ ] 다른 사용자 행의 `SELECT`, `INSERT`, `UPDATE`, `DELETE`가 모두 거부됨
- [ ] 위조한 `user_id`와 다른 사용자의 부모 FK 연결이 거부됨
- [ ] migration을 빈 DB에 처음부터 적용할 수 있음
- [ ] rollback 또는 후속 수정 전략이 있음
- [ ] 실제 키·토큰·프로젝트 비밀값이 diff에 없음
- [ ] 관련 API 타입과 문서를 함께 갱신함
- [ ] 테스트와 빌드 결과를 PR에 기록함

## 충돌이 났을 때

migration 충돌을 단순히 두 SQL 파일의 문장을 이어 붙여 해결하지 않는다. 먼저 다음을 비교한다.

1. 두 변경이 같은 개념을 다른 이름으로 만들었는가?
2. 동일 컬럼의 타입·null 허용·기본값이 다른가?
3. FK와 삭제 정책이 다른가?
4. RLS가 한쪽 변경에만 있는가?
5. 프론트와 FastAPI가 어느 계약을 이미 사용 중인가?

중복 설계라면 하나의 정식 모델로 합의한 후 새 migration으로 정리한다. 이미 공유 환경에 적용된 migration을 고쳐서 이력을 숨기지 않는다.

## 기존 브랜치 주의

`hw/planner-core`와 `hw/refactor-frontend-structure`는 squash 병합된 이전 브랜치다. Git이 미병합 브랜치처럼 표시할 수 있지만 기능은 이미 `main`에 들어가 있으므로 다시 병합하지 않는다. 새 작업은 최신 `origin/main`에서 시작한다.
