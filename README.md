# PlannerKK

프로젝트 일정, 오늘의 계획, 캘린더, 기억을 한곳에서 관리하는 AI 플래너 프로젝트입니다.

> 현재는 React + Vite 기반 UI 프로토타입입니다. AI 에이전트와 백엔드는 이후 단계에서 연동합니다.

## 시작하기

### 1. 저장소 복제

```bash
git clone https://github.com/hwc2000/plannerkk.git
cd plannerkk
```

### 2. 의존성 설치

```bash
npm install
```

### 3. 개발 서버 실행

```bash
npm run dev
```

터미널에 표시되는 주소(기본값: `http://localhost:5173`)를 브라우저에서 엽니다.

## 사용 가능한 명령어

| 명령어 | 설명 |
| --- | --- |
| `npm run dev` | 개발 서버 실행 |
| `npm run build` | TypeScript 검사 및 프로덕션 빌드 |
| `npm run preview` | 빌드 결과를 로컬에서 미리보기 |

## 현재 화면

- 오늘
- 캘린더
- 전체 계획
- 기억

## 기술 스택

- React
- TypeScript
- Vite
- lucide-react

## 협업 규칙

1. 작업 전 최신 `main` 브랜치를 받습니다.
2. 기능별 브랜치에서 작업합니다. 예: `feature/calendar-input`
3. `npm run build`가 성공하는지 확인한 뒤 커밋합니다.
4. 작업 내용을 GitHub Pull Request로 올린 뒤 `main`에 병합합니다.

## 향후 예정

- Supabase 로그인 및 데이터베이스 연동
- 프로젝트·마일스톤·캘린더 데이터 CRUD
- FastAPI 백엔드
- LangChain / LangGraph 기반 단일 AI 플래닝 에이전트
