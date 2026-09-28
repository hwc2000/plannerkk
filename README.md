# PlannerKK

프로젝트 일정, 단계별 할 일, 캘린더, 기억을 한곳에서 관리하고 AI에게 프로젝트 계획 초안을 요청할 수 있는 플래너입니다.

현재 데이터는 브라우저 `localStorage`에 저장됩니다. AI 계획은 **초안 생성 → 사용자 검토 → 단계별 할 일 반영** 순서로 동작하며, 생성만으로는 저장되지 않습니다.

> **현재 Supabase 프로젝트, Supabase Auth, 데이터베이스 스키마 및 migration은 아직 없습니다.**
> 프로젝트·일정·기억 CRUD는 로컬 UI 프로토타입이며, 로그인 사용자별 서버 저장 기능으로 오해하면 안 됩니다.

## 기술 스택

- React + TypeScript + Vite
- FastAPI + Pydantic
- OpenAI `gpt-4o-mini` Structured Outputs
- Vitest + Testing Library / Python `unittest`

## 로컬 실행

### 1. 저장소와 의존성 준비

```bash
git clone https://github.com/hwc2000/plannerkk.git
cd plannerkk
npm install
python3 -m pip install -r requirements.txt
```

### 2. 서버 환경변수 설정

```bash
cp .env.example .env
```

`.env`의 `OPENAI_API_KEY`를 실제 키로 바꿉니다.

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_PLAN_MODEL=gpt-4o-mini
FRONTEND_ORIGIN=http://localhost:5173
```

> `.env`는 Git에서 제외됩니다. OpenAI 키에 `VITE_` 접두사를 붙이거나 React 코드에 넣으면 브라우저에 노출되므로 반드시 FastAPI 서버에서만 사용합니다.

### 실행·배포 보안 범위

현재 AI API는 **개인 로컬 개발용**입니다. `npm run dev`와 문서의 Uvicorn 명령은 모두 `127.0.0.1`에만 바인딩되며, 요청 문자열·기존 할 일 수·AI 결과 항목 수에도 상한을 둡니다.

인증과 요청 제한은 아직 구현하지 않았습니다. 따라서 현재 상태로 FastAPI 포트를 외부 네트워크에 공개하거나 공용 서비스로 배포하면 안 됩니다. 공개·공유 배포 전에는 최소한 다음 보호 장치를 추가해야 합니다.

- 사용자 인증·권한 확인
- 사용자/IP별 요청 속도 및 일일 사용량 제한
- 요청 본문 크기 제한과 사용량·비용 모니터링
- 운영 환경의 제한된 CORS 허용 출처 설정

### 3. FastAPI 실행 — 터미널 1

```bash
python3 -m uvicorn server.app.main:app --reload --host 127.0.0.1 --port 8000 --env-file .env
```

상태 확인: `http://127.0.0.1:8000/api/health`

### 4. React 실행 — 터미널 2

```bash
npm run dev
```

브라우저에서 `http://localhost:5173`을 엽니다. Vite가 `/api` 요청을 FastAPI의 `8000` 포트로 프록시합니다.

## AI 계획 사용법

1. 프로젝트를 먼저 생성하거나 기존 프로젝트를 선택합니다.
2. 사이드바에서 `오늘`을 엽니다.
3. 필요한 계획을 자연어로 입력하고 `계획 초안 만들기`를 누릅니다.
4. AI가 제안한 단계, 날짜, 예상 시간을 검토합니다.
5. 확정할 때만 `검토 후 단계별 할 일에 반영`을 누릅니다.

## 검사 명령어

| 명령어 | 설명 |
| --- | --- |
| `npm run dev` | React 개발 서버 실행 |
| `npm test` | 프론트엔드 테스트 실행 |
| `npm run build` | TypeScript 검사 및 프로덕션 빌드 |
| `npm run preview` | 빌드 결과 미리보기 |
| `python3 -m unittest discover -s server/tests -v` | FastAPI·OpenAI 계획 로직 테스트 |

## 현재 구현 범위

- 브라우저 `localStorage` 기반 프로젝트·단계별 할 일 CRUD
- 브라우저 `localStorage` 기반 캘린더 일정 CRUD
- 브라우저 `localStorage` 기반 기억 CRUD
- 프로젝트별 AI 계획 초안 생성 및 검토 후 반영
- FastAPI 상태 확인 및 AI 계획 초안 API

## 아직 구현되지 않은 범위

- Supabase 프로젝트와 공용 개발 환경
- Supabase Auth 기반 로그인·회원가입 및 사용자 세션
- DB 스키마, RLS 정책 및 migration
- `user_profiles` 성향 온보딩
- 프로젝트·마일스톤·일정·기억의 서버/DB CRUD
- 전체 계획 화면용 달성률·마감일·위험도 계산 API
- LangGraph `PlannerState`, DB 컨텍스트 로드, 채팅 및 전체 재조정 흐름
- AI 기억 후보 생성·사용자 승인 저장과 검증 실패 재생성 순환

## 데이터베이스 도입 전 협업 기준

Supabase가 아직 없으므로 팀원이 각자 별도 테이블을 구현하지 않습니다. 먼저 [Supabase 도입 및 데이터 계약](docs/architecture/supabase-foundation.md)을 검토·합의한 뒤 공용 프로젝트와 최초 migration을 만듭니다.

- 합의 전 Supabase 대시보드에서 테이블을 임의 생성하지 않습니다.
- Supabase 생성 이후에는 `supabase/migrations/*.sql`을 스키마의 기준으로 사용합니다.
- `main`에 병합된 migration을 수정하지 않고 새 migration을 추가합니다.
- 팀 작업 순서와 PR 규칙은 [DB 협업 워크플로](docs/collaboration/database-workflow.md)를 따릅니다.
- 서비스 키와 실제 환경변수는 Git에 커밋하지 않습니다.

## 협업 규칙

1. 작업 전 최신 `main` 브랜치를 받습니다.
2. 기능별 브랜치에서 작업합니다. 현우 작업 브랜치는 `hw/...` 이름을 사용합니다.
3. 공용 타입, API, DB 계약을 바꿀 때 관련 문서와 migration을 함께 갱신합니다.
4. 프론트엔드 테스트, 백엔드 테스트, 빌드를 모두 확인합니다.
5. 작업 내용을 Pull Request로 올려 검토한 뒤 `main`에 병합합니다.
6. squash 병합된 이전 기능 브랜치를 다시 `main`에 병합하지 않습니다.

## 향후 예정

- Supabase 기반 인증·RLS·데이터베이스 연동
- LangGraph 기반 복합 계획·재계획 흐름
- AI 제안 변경사항의 세부 편집 및 승인 기록
