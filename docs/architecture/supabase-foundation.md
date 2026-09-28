# Supabase 도입 및 데이터 계약 초안

## 문서 상태

- 상태: **설계 초안 — 아직 구현되지 않음**
- 현재 저장 방식: 브라우저 `localStorage`
- 현재 존재하지 않는 것: Supabase 프로젝트, Auth 연결, DB 테이블, RLS 정책, migration, 생성된 DB 타입
- 목적: 팀원이 각자 다른 스키마를 만들기 전에 공용 데이터 경계를 합의한다.

이 문서는 실제 DB가 존재한다는 뜻이 아니다. 팀 합의와 공용 Supabase 프로젝트 생성 전에는 SQL을 사실처럼 취급하거나 기능 완료로 보고하지 않는다.

## 도입 순서

1. 팀 소유의 Supabase 개발 프로젝트와 관리자 지정
2. 리전, 프로젝트 접근 권한, 비밀값 공유 방식 합의
3. 이 문서의 테이블명·관계·삭제 정책 검토
4. Supabase CLI 초기화 및 최초 migration 작성
5. migration을 빈 DB에 적용해 재현 가능성 검증
6. Auth 및 RLS 정책 검증
7. 생성된 타입과 FastAPI 인증 경계 연결
8. `localStorage` CRUD를 API/DB CRUD로 단계적으로 교체

합의 전에는 팀원이 Supabase 대시보드에서 테이블을 따로 만들지 않는다. 프로젝트 생성 이후에도 대시보드의 현재 상태가 아니라 Git의 `supabase/migrations/*.sql`을 스키마 기준으로 사용한다.

## 제안 아키텍처

```text
React
  ├─ Supabase Auth: 로그인·회원가입·세션 획득
  └─ Bearer access token과 함께 FastAPI 호출
        ├─ 사용자 토큰 검증
        ├─ 요청 사용자의 데이터만 조회·변경
        ├─ 프로젝트/일정/기억 CRUD
        └─ 필요한 최소 컨텍스트만 OpenAI에 전달
              └─ 구조화 결과 반환 → 서버 검증 → 사용자 승인 후 저장
```

기본 제안은 앱 데이터 CRUD를 FastAPI 경계에 모으는 것이다. React가 Supabase 테이블을 직접 읽는 구조로 변경하려면 팀 합의와 RLS 테스트를 먼저 추가한다. 두 접근을 기능별로 임의 혼용하지 않는다.

FastAPI의 일반 사용자 CRUD는 요청의 Supabase access token을 검증하고, 해당 사용자 JWT가 적용된 Supabase 클라이언트로 DB에 접근하는 방식을 기본으로 한다. 이 경우 RLS가 실제 요청 사용자 기준으로 동작해야 한다. `service_role`은 RLS를 우회하므로 일반 사용자 CRUD에 기본 사용하지 않는다. 관리·백그라운드 작업에서 예외적으로 사용할 때는 endpoint를 분리하고 서버가 사용자 소유권을 직접 강제하며 별도 권한 테스트를 둔다.

## 보안 경계

- React에는 Supabase의 공개용 URL과 publishable/anon key만 둘 수 있다.
- `service_role` 키, DB 비밀번호, OpenAI 키는 React 코드나 `VITE_` 환경변수에 넣지 않는다.
- FastAPI는 로그인 사용자의 식별자를 클라이언트 본문에서 신뢰하지 않고 검증된 토큰에서 가져온다.
- 모든 사용자 소유 테이블에 RLS를 활성화하고 `SELECT`, `INSERT`, `UPDATE`, `DELETE` 각각에서 `auth.uid() = user_id`를 검증한다.
- `service_role`은 RLS를 우회한다. 백엔드에서 사용하더라도 RLS가 보호해 줄 것이라고 가정하지 않는다.
- 자식 행은 같은 사용자가 소유한 부모만 참조할 수 있어야 한다. 위조한 `user_id`와 다른 사용자의 `project_id` 조합을 DB 제약과 권한 테스트로 거부한다.
- AI에는 DB 접속 정보, 인증 토큰, 다른 사용자 데이터, 불필요한 개인정보를 전달하지 않는다.
- 실제 키와 프로젝트 식별자는 `.env.example`에 값 없이 이름만 기록한다.

## 도메인 및 담당 경계

| 영역 | 제안 테이블 | 담당 | 현재 상태 |
| --- | --- | --- | --- |
| 인증 | Supabase `auth.users` | 공용 기반 | 미도입 |
| 온보딩·성향 | `user_profiles` | 최민서 | 미구현 |
| 프로젝트 | `projects` | 최현우 | `localStorage` 프로토타입 |
| 단계별 할 일 | `milestones` | 최현우 | `localStorage` 프로토타입 |
| 캘린더 일정 | `calendar_events` | 최현우 | `localStorage` 프로토타입 |
| 기억 | `memories` | 최현우 | 수동 기억 `localStorage` 프로토타입 |
| 달성률·마감·위험 | 기존 테이블 기반 계산 API | 이준현 | 미구현 |
| AI 계획·재조정 | 기존 데이터의 서버 조회 및 구조화 결과 | 공용 AI 흐름 | 단일 계획 초안만 구현 |

달성률·위험도를 처음부터 별도 원본 테이블로 중복 저장하지 않는다. `projects`, `milestones`, `calendar_events`에서 계산하고, 성능이나 이력 요구가 확인될 때 캐시·스냅샷 테이블을 별도 제안한다.

## 공통 컬럼 초안

사용자 소유 테이블은 원칙적으로 다음 필드를 가진다.

```sql
id uuid primary key default gen_random_uuid(),
user_id uuid not null references auth.users(id) on delete cascade,
created_at timestamptz not null default now(),
updated_at timestamptz not null default now()
```

실제 SQL은 최초 migration PR에서 확정한다. `updated_at` 자동 갱신 방식도 그 PR에서 공용 함수 또는 애플리케이션 책임 중 하나로 결정한다.

## 테이블 초안

아래 목록은 현재 TypeScript 모델을 DB 계약으로 옮기기 위한 출발점이며 아직 확정 스키마가 아니다.

### `user_profiles`

- `user_id`: `auth.users.id`를 참조하는 `PRIMARY KEY` 또는 `UNIQUE`로 1:1 강제
- 표시 이름 및 온보딩 완료 여부
- 계획 성향과 기본 가용시간 등 합의된 설정
- 민감하거나 자유형인 성향 데이터는 필요한 항목만 저장

### `projects`

- `id`, `user_id`
- `title`, `goal`
- `start_date`, `due_date`
- `priority`: `high | medium | low`
- `status`: `active | completed | paused`

자식 테이블이 소유권까지 참조할 수 있도록 `(id, user_id)`에 `UNIQUE` 제약을 두는 방안을 최초 migration에서 검증한다.

### `milestones`

- `id`, `user_id`, `project_id`
- `title`
- `start_date`, `due_date`
- `estimated_hours`
- `status`: `todo | in_progress | done | deferred`

관계: 프로젝트가 삭제되면 해당 프로젝트에 종속된 마일스톤도 삭제한다 (`ON DELETE CASCADE`).

`milestones.user_id`와 부모 `projects.user_id`가 반드시 같아야 한다. `(project_id, user_id)` 복합 FK처럼 DB가 강제할 수 있는 제약을 사용하고, RLS도 같은 사용자 소유 프로젝트인지 확인한다.

### `calendar_events`

- `id`, `user_id`
- `project_id`: 선택값
- `title`
- 일정 시각: `starts_at`·`ends_at`을 `timestamptz`로 저장하는 안을 우선 검토
- `is_fixed`

관계: 프로젝트가 삭제돼도 독립 일정은 보존하고 `project_id`만 비운다. 복합 FK를 사용한다면 `user_id`까지 `NULL`이 되지 않도록 `ON DELETE SET NULL (project_id)`처럼 대상 컬럼을 명확히 지정할 수 있는지 최초 migration에서 검증한다.

선택한 프로젝트가 있다면 `calendar_events.user_id`와 `projects.user_id`가 같아야 한다. nullable 관계의 소유권을 보장하는 복합 FK, 제약 함수 또는 trigger 중 하나를 최초 migration에서 채택하고, RLS의 `INSERT`·`UPDATE` 정책에서도 다른 사용자 프로젝트 연결을 거부한다.

현재 UI의 `date`·`startTime`·`endTime`을 `timestamptz`로 변환할 기준 시간대가 필요하다. 기본 IANA 시간대 저장 위치와 DST 처리 방식을 합의하기 전에는 일정 컬럼을 확정하지 않는다.

### `memories`

- `id`, `user_id`
- `content`, `category`
- `source`: 현재 `user | ai_approved`
- 생성 시각 및 필요 시 수정 시각

AI 기억 후보 기능을 구현할 때 `candidate`, `approved`, `rejected` 상태와 승인 이력을 별도 모델로 둘지 먼저 결정한다. 현재 `memories`에 미승인 AI 결과를 바로 저장하지 않는다.

## 명명 및 변환 규칙

- DB 테이블·컬럼: `snake_case`
- TypeScript/Pydantic API 필드: 기존 프론트 계약을 고려해 `camelCase` 사용 가능
- DB와 API 사이의 변환을 repository/service 계층에 모은다.
- 프론트 컴포넌트가 DB 컬럼명을 직접 알게 하지 않는다.
- 프로젝트·마일스톤처럼 하루 단위인 값은 `date`를 사용한다.
- 일정 시각은 사용자 IANA 시간대를 기준으로 `timestamptz`에 변환하는 방안을 우선 사용하되, 시간대 저장 위치와 DST 정책을 최초 migration 전에 확정한다.

## 현재 구현에서 반드시 해결할 통합 문제

1. 프로젝트 폼은 빈 `goal`을 허용하지만 AI API의 프로젝트 목표는 최소 1자다.
2. AI 요청 UI는 1~2자 입력을 보낼 수 있지만 서버 요청은 최소 3자다.
3. 현재 `today` 화면은 실제 오늘 일정이 아니라 프로젝트 AI 초안 화면이다.
4. `localStorage` 값은 JSON 파싱 외 스키마 검증과 버전 migration이 없다.
5. AI 초안 승인은 생성 작업을 단순 추가하므로 중복 승인 방지와 DB transaction이 없다.
6. AI API는 인증·사용자별 권한·rate limit이 없어 외부 공개용이 아니다.
7. 일반 CRUD 자동 테스트는 아직 없고 AI 흐름 테스트에 집중되어 있다.
8. 달성률·마감일·위험도 API는 아직 존재하지 않는다.

각 구현 PR은 관련 문제를 해결하거나, 해결하지 않는다면 PR의 제외 범위에 명시한다.

## 최초 DB PR 완료 조건

- [ ] 공용 Supabase 개발 프로젝트와 관리 책임자가 정해짐
- [ ] `supabase/config.toml` 및 최초 migration이 Git에 존재함
- [ ] 빈 로컬/테스트 DB에서 migration을 처음부터 적용 가능함
- [ ] 테이블명, FK, 삭제 정책, enum/check 제약이 문서와 일치함
- [ ] 사용자 소유 테이블 RLS가 활성화됨
- [ ] RLS가 `SELECT`·`DELETE`의 `USING`, `INSERT`의 `WITH CHECK`, `UPDATE`의 `USING`과 `WITH CHECK`를 구분해 적용함
- [ ] 일반 사용자 CRUD가 사용자 JWT 컨텍스트로 실행되고 `service_role`에 암묵적으로 의존하지 않음
- [ ] 본인 소유 행의 `SELECT`, `INSERT`, `UPDATE`, `DELETE`가 모두 성공함
- [ ] 다른 사용자 행의 `SELECT`, `INSERT`, `UPDATE`, `DELETE`가 모두 거부됨
- [ ] 위조한 `user_id` 및 다른 사용자 부모를 가리키는 FK 연결이 거부됨
- [ ] 실제 비밀값이 Git 이력과 프론트 번들에 없음
- [ ] `.env.example`에는 변수 이름과 안전한 예시만 있음
- [ ] README의 현재 구현 범위가 실제 상태에 맞게 갱신됨
