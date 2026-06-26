# EqualView

시각장애인을 위한 AI 화면해설 자동생성 서비스.
영화 영상을 입력받아 대사가 없는 침묵 구간을 감지하고, AI가 생성한 한국어 화면해설 음성을 삽입해 합성된 결과물을 출력합니다.

---

## 현재 MVP 범위

| 단계 | 상태 |
|------|------|
| 영상 업로드 + Job API | ✅ |
| ffmpeg 오디오 추출 | ✅ |
| Whisper 전사 + speech/non_speech 분석 | ✅ |
| Celery 비동기 Worker | ✅ |
| Gemini / TTS / 합성 MP4 | ❌ (예정) |

완료 시 결과: `uploads/{job_id}/segments.json` (대사·침묵 구간 JSON)

---

## 빠른 시작

### 방법 A — Docker Compose (권장)

**사전 요구사항:** Docker, Node.js 18+ (프론트만)

```bash
git clone <repo-url>
cd EqualView

# 백엔드 전체 (API + Worker + Redis)
docker compose up --build
# 또는
make up
```

| 서비스 | URL |
|--------|-----|
| API / Swagger | http://localhost:8000/docs |
| Redis | 6379 (호스트 venv 개발용, Docker 내부는 `redis:6379`) |

프론트엔드 (별도 터미널):

```bash
cd frontend && npm install && npm run dev
# 또는: make frontend
```

→ http://localhost:5173

종료:

```bash
docker compose down
# 또는: make down
```

---

### 방법 B — 로컬 venv (Docker 없이 백엔드)

**사전 요구사항:** Python 3.10+, Node.js 18+, Docker (Redis만)

```bash
make setup          # venv + npm + Redis 컨테이너
make api            # 터미널 1
make worker         # 터미널 2
make frontend       # 터미널 3
```

시스템 ffmpeg는 **필수 아님** (`imageio-ffmpeg` 포함).

---

## Make 명령어

```bash
make help       # 명령어 목록

# Docker
make up         # docker compose up --build
make down       # 컨테이너 종료
make logs       # api/worker 로그

# 로컬 venv
make setup      # 의존성 설치
make redis      # Redis 컨테이너만 기동
make api
make worker
make frontend
```

---

## Docker Compose 구성

| 서비스 | 역할 | 포트 |
|--------|------|------|
| `redis` | Celery broker | (내부) |
| `api` | FastAPI | 8000 |
| `worker` | Celery Worker | — |

- **같은 Dockerfile** (`backend/Dockerfile`)을 api/worker가 공유
- **공유 volume:** `uploads_data` → `/app/uploads` (Job 파일)
- **Whisper 캐시 volume:** `whisper_cache` (모델 재다운로드 방지)

환경 변수 (compose에서 주입):

```env
REDIS_URL=redis://redis:6379/0
UPLOAD_DIR=/app/uploads
```

---

## API 개요

| Method | Path | 설명 |
|--------|------|------|
| `POST` | `/api/jobs` | 영상 업로드 → `{ job_id, status: "PENDING" }` |
| `GET` | `/api/jobs/{job_id}` | Job 상태 폴링 |
| `GET` | `/api/jobs/{job_id}/segments` | 분석 결과 (COMPLETED 후) |
| `POST` | `/api/extract-audio` | 레거시 동기 API (유지) |

---

## 아키텍처

```
Frontend (:5173, host)
    │  /api → proxy
    ▼
FastAPI (:8000) ──enqueue──► Redis ──► Celery Worker
    │                                      │
    └─ uploads volume (job.json, segments) ◄┘
```

Job 상태는 Redis가 아니라 **`uploads/{job_id}/job.json`** (공유 volume)에 저장됩니다.

---

## 폴더 구조

```
EqualView/
├── backend/
│   ├── Dockerfile
│   ├── api/
│   ├── pipeline/
│   ├── services/
│   ├── tasks/
│   └── celery_app.py
├── frontend/
├── docker-compose.yml
├── Makefile
└── scripts/setup.sh
```

---

## 환경 변수

로컬 venv용 `backend/.env` (`make setup` 시 생성):

```env
REDIS_URL=redis://localhost:6379/0
```

Docker Compose는 `docker-compose.yml`의 `environment`로 자동 설정합니다.

---

## 트러블슈팅

### `vite: command not found`

```bash
cd frontend && npm install
```

### Job이 PENDING에서 멈춤 (Docker)

```bash
docker compose logs worker
docker compose ps
```

Worker 컨테이너가 `running`인지 확인.

### Job이 PENDING (로컬 venv)

`make worker` 실행 여부 확인.

### 포트 8000 충돌

다른 프로세스가 8000 사용 중. 종료 후 `make up` 재시도.

### Whisper 첫 실행이 느림

최초 1회 모델 다운로드 (~150MB, 네트워크 필요). `whisper_cache` volume에 캐시됩니다.

### Docker 볼륨 데이터 초기화

```bash
docker compose down -v
```

---

## 목표 파이프라인 (전체)

```
영상 업로드 → Whisper → 프레임 추출 → Gemini → TTS → ffmpeg 합성 → MP4 출력
```

현재는 Whisper + segment 분석까지 구현되어 있습니다.
