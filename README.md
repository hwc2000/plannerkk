# PlannerKK

프로젝트 일정, 단계별 할 일, 캘린더, 기억을 한곳에서 관리하고 AI에게 프로젝트 계획 초안을 요청할 수 있는 플래너입니다.

기존 프로젝트·할 일·수동 캘린더·기억은 브라우저 `localStorage`에 저장됩니다. 추가된 실행 프로필·가용 시간·주간 계획·완료 상태는 SQLite DB에 저장됩니다. **Supabase와 로그인 기능은 아직 없습니다.** 기존 AI 계획은 **초안 생성 → 사용자 검토 → 단계별 할 일 반영** 순서로 동작합니다. 새 주간 플래너는 DB에 초안을 저장하고, 확정한 뒤 캘린더에 반영합니다.

**추가 기능과 간편 실행: [INTEGRATION.md](INTEGRATION.md)** — `python run_local.py`로 빌드된 화면과 API를 `http://127.0.0.1:8010`에서 함께 실행합니다.

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

## 현재 상태

구현됨:

- 브라우저에 저장되는 프로젝트·할 일·캘린더·기억 관리
- AI 계획 초안 생성 → 사용자 확인 → 할 일 반영
- 실행 프로필 온보딩, 규칙 기반/LLM 분석, 수정·확정·초기화·JSON 내보내기
- 요일별 가용 시간, 구체적인 주간 시간 배치, 체크리스트 전환 및 완료 상태 동기화
- SQLite 저장 및 확정 계획의 기존 캘린더 연동

아직 안 됨:

- Supabase, 로그인·회원가입, 사용자별 DB 저장
- 달성률·마감일·위험도 API
- LangGraph 채팅·전체 재조정·AI 기억 승인

## 팀 작업 기준

지금 단계에서는 Supabase를 사용하지 않습니다. 각자 만든 기능을 합칠 수 있도록 **localStorage 키와 객체 필드 이름을 똑같이 사용합니다.**

### localStorage 키

| 저장 데이터 | 키 | 타입 |
| --- | --- | --- |
| 프로젝트 | `replan-projects-v1` | `Project[]` |
| 단계별 할 일 | `replan-milestones-v1` | `Milestone[]` |
| 캘린더 일정 | `replan-events-v1` | `CalendarEvent[]` |
| 기억 | `replan-memories-v1` | `Memory[]` |

### 객체 필드 이름

- `Project`: `id`, `title`, `goal`, `startDate`, `dueDate`, `priority`, `status`
- `Milestone`: `id`, `projectId`, `title`, `startDate`, `dueDate`, `estimatedHours`, `status`
- `CalendarEvent`: `id`, `title`, `date`, `startTime`, `endTime`, `projectId`, `isFixed`
- `Memory`: `id`, `content`, `category`, `source`, `createdAt`

값도 아래 문자열로 통일합니다.

- `priority`: `high | medium | low`
- 프로젝트 `status`: `active | completed | paused`
- 할 일 `status`: `todo | in_progress | done | deferred`
- `category`: `availability | preference | priority | context`
- `source`: `user | ai_approved`
- `CalendarEvent.projectId`만 선택값이며, 나머지 필드는 필수입니다.

꼭 지킬 것:

1. 위 이름을 그대로 사용하고 비슷한 이름의 키나 필드를 새로 만들지 않습니다.
2. 필드 이름은 `camelCase`를 사용합니다. 예: `startDate`, `projectId`.
3. 날짜는 `YYYY-MM-DD`, 시간은 `HH:mm`, `id`는 문자열로 저장합니다.
4. 스키마 기준은 `src/shared/types.ts`입니다. 바꿔야 하면 먼저 팀에 알리고 이 파일부터 함께 수정합니다.
5. 작업 전 최신 `main`에서 새 브랜치를 만들고, 작업 후 테스트와 빌드를 확인해 Pull Request를 올립니다.

> 현재 데이터는 각자의 브라우저에 따로 저장됩니다. 브라우저끼리 데이터를 공유하는 기능은 아직 없습니다.
