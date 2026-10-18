# 자동 테스트와 시연 URL

## PR 자동 테스트 (GitHub Actions)

`.github/workflows/ci.yml`이 PR을 올리거나 `main`에 푸시할 때마다 실행됩니다.

| 작업 | 내용 |
| --- | --- |
| Frontend | `npm ci` → `npm test`(Vitest) → `npm run build`(타입 검사 + 빌드) |
| Backend | `pip install -r requirements.txt` → `python -m unittest server/tests/test_*.py` |

테스트는 가짜 AI 응답을 사용하므로 OpenAI 키나 비밀값이 필요 없습니다.
실패한 PR의 머지를 막으려면 저장소 관리자가 Settings → Branches → `main` 보호 규칙에서
`Frontend (types, tests, build)`와 `Backend (unit tests)`를 필수 검사로 지정합니다.

## 시연 URL (Render)

`Dockerfile` 하나로 React 빌드 결과와 FastAPI를 같은 주소에서 제공합니다.

1. [Render](https://render.com)에 GitHub 계정으로 로그인합니다.
2. New → Blueprint → 이 저장소를 선택하면 `render.yaml`대로 `replan-demo` 서비스가 만들어집니다.
3. 비밀값 두 개를 입력합니다.
   - `OPENAI_API_KEY`: 서버에서만 쓰는 키
   - `DEMO_PASSWORD`: 시연 URL 접속 비밀번호 (사용자 이름은 아무거나)
4. 배포가 끝나면 `https://replan-demo.onrender.com` 같은 주소가 생깁니다. 이후 `main`에 머지될 때마다 자동으로 다시 배포됩니다.

로컬에서 같은 이미지를 확인하려면:

```bash
docker build -t replan-demo .
docker run --rm -p 8000:8000 -e DEMO_PASSWORD=test -e OPENAI_API_KEY=sk-... replan-demo
```

## 시연 전 확인할 제약

- **비용:** `DEMO_PASSWORD`는 접근만 막습니다. 요청 횟수 제한은 없으므로 OpenAI 대시보드에서 월 사용 한도를 설정합니다.
- **사용자 구분 없음:** 로그인 기능이 없어 접속한 모두가 하나의 프로필과 계획을 함께 씁니다. 시연 전용입니다.
- **데이터 초기화:** 무료 플랜은 재배포·재시작 때 SQLite 파일(`/app/data`)이 사라집니다. 유지하려면 유료 디스크를 `/app/data`에 연결하거나 공용 DB로 옮깁니다.
- **첫 접속 지연:** 무료 플랜은 쉬고 있다가 첫 요청에 30~50초가 걸립니다. 시연 직전에 한 번 열어 둡니다.
- **브라우저 데이터:** 프로젝트·일정·기억은 브라우저 저장소에 있어 기기마다 따로입니다.
