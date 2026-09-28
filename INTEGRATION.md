# 실행 프로필 · 주간 계획 통합

기존 React/TypeScript와 FastAPI 구조에 실행 프로필 및 주간 플래너를 추가했습니다. 기존 `오늘`의 프로젝트 초안 생성 기능도 유지됩니다.

## 실행

처음 실행할 때 프론트엔드를 빌드하고 Python 환경을 준비하세요. `dist`는 Git에 포함되지 않습니다.

```powershell
npm ci
npm run build
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

실행:

```powershell
.\.venv\Scripts\python.exe run_local.py
```

또는 `./start.ps1`. 기본 주소는 http://127.0.0.1:8010 입니다. 브라우저를 자동으로 열거나 조작하지 않습니다. 종료는 실행 터미널의 Ctrl+C입니다. 변경한 프론트엔드를 반영하려면 `npm run build` 후 서버를 다시 시작하세요. 기존 Vite 개발 방법(5173 → API 8000)도 그대로 지원합니다. 이전 프로토타입 서버가 8000을 사용 중이라면 먼저 해당 서버를 종료하세요.

키는 프로젝트 `.env`의 `OPENAI_API_KEY`에 저장합니다. 기존 프로젝트의 `OPENAI_PLAN_MODEL=gpt-4o-mini` 설정을 사용합니다. 별도 프로필 미리보기에는 키가 필요 없습니다. `python setup_api.py`로 숨김 입력 등록도 가능합니다. 키는 브라우저로 반환하지 않습니다.

## 사용하는 순서

1. 메뉴의 **실행 프로필·주간 계획** 또는 **설정**을 엽니다.
2. 생활 형태·생활 규칙성·실행 장애·집중 시간·계획 변경 대응을 답합니다.
3. 규칙 기반 또는 LLM 프로필 초안을 확인하고 확정합니다. 사실과 초기 추천 설정은 분리됩니다.
4. 월~일 08~23시 가용 시간과 시간 플래너/할 일 플래너 중 하나를 선택합니다. 가용 시간은 별도로 저장 가능하며 생성 시에도 저장합니다.
5. 자유 목표 또는 기존 프로젝트를 선택해 시작일부터 7일의 구체적인 계획 초안을 생성합니다.
6. 검토 후 확정하면 캘린더에 즉시 표시됩니다. 두 플래너 화면의 완료 상태는 동일한 DB 작업을 참조합니다.

LLM은 작업·예상 시간·완료 조건·마감을 제안합니다. 서버가 집중 구간, 휴식, 여유분, 과거 시간, 프로젝트 기간, 기존 캘린더 일정과의 충돌을 검증하며 실제 시간을 배치합니다. 고정 일정 자유 설명만으로 강제 차단하지 않으므로 실제 일정은 캘린더에도 등록해야 합니다. 입력한 주간 가용 시간이 주간 계획의 시간 예산 기준입니다.

시간이 부족하거나 마감 안에 못 넣은 작업은 별도 목록에 표시됩니다. 프로필과 가용 시간을 변경하면 새 계획부터 반영됩니다. 계획 확정 시 이전 주간 계획을 대체하며, 이전 완료 상태도 대체됩니다. 자동 재계획 및 반복 일정은 아직 없습니다.

## 저장

- 새 프로필·프로필 초안·가용 시간·플래너 방식·주간 계획 초안/확정·체크 상태: `data/replan.sqlite3`. Python 내장 SQLite이며 별도 설치 불필요.
- 기존 프로젝트·단계별 할 일·수동 캘린더 일정·기억: 기존 localStorage 키와 객체 구조 유지.
- 주간 계획 일정은 복사본을 localStorage에 중복 생성하지 않고 확정 계획에서 캘린더 항목을 도출합니다. 편집은 주간 계획 화면에서 수행합니다.
- 브라우저 저장 데이터는 주소/포트별로 구분됩니다. 기존 데이터를 사용할 때는 기존 접속 주소를 유지하세요.
- 새 모듈의 JSON 필드도 camelCase이며 `src/shared/types.ts`에 정의했습니다.
- DB는 로컬 사용자 1명을 위한 최신 상태입니다. 로그인이나 사용자별 분리는 포함하지 않습니다.
- 초기화는 실행 프로필·시간표·주간 계획만 삭제하며 기존 프로젝트·수동 일정·기억은 유지합니다.
- JSON 내보내기 지원. 이전 프로토타입의 DB와 개인 답변은 자동 이관하지 않습니다.

## API

`GET /api/execution`으로 전체 상태와 revision을 읽습니다. 변경 요청에는 최신 revision이 필요합니다. 오래된 요청은 HTTP 409로 거절하여 다른 탭의 저장이나 초기화 결과를 덮어쓰지 않습니다.

- `POST /profile`: answers, mode(demo/llm), consent → 프로필 초안
- `POST /profile/confirm`: 초안 확정
- `PUT /settings`: slots(day 월=0~일=6, hour=8~22), view
- `POST /plan`: goal, startDate, consent, project, existingTasks, events → 계획 초안
- `POST /plan/confirm`: planId, 현재 project/events → 충돌 재검사 후 확정
- `POST /plan/discard`: 계획 초안 버리기
- `POST /task`: planId, taskId, completed
- `POST /reset`: 실행 데이터 초기화

모든 경로의 접두사는 `/api/execution`입니다. LLM 오류와 키·사용 한도 오류는 사용자에게 표시합니다. 조용히 데모 결과로 대체하지 않습니다.

## 검증

```powershell
python -m unittest discover -s server/tests -v
npm test
npm run build
```

백엔드 23개, 프론트엔드 15개 테스트 및 TypeScript/프로덕션 빌드를 통과했습니다. 테스트는 별도 임시 DB와 가상 LLM 응답을 사용합니다. 실제 사용자의 DB나 브라우저를 조작하는 자동 테스트는 실행하지 않았습니다.

OpenAI 구조화 응답 참고: https://developers.openai.com/api/docs/guides/structured-outputs
