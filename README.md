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
| 얼굴 인식 (person_001, 2, ... + bounding box) | ✅ |
| Celery 비동기 Worker | ✅ |
| Gemini 화면해설 생성 (대사 맥락 + 프레임 반영) | ✅ |
| TTS 음성 합성 (edge-tts, 무료) | ✅ |
| ffmpeg 최종 영상 합성 (`output.mp4`) | ✅ |

완료 시 결과: `uploads/{job_id}/segments.json` (대사·침묵 구간 + 화면해설 텍스트 JSON), `uploads/{job_id}/output.mp4` (화면해설 음성이 삽입된 최종 영상)

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
| `GET` | `/api/jobs/{job_id}/download` | 최종 영상(mp4) 다운로드 (combine_status COMPLETED 후) |
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
영상 업로드 → Whisper(대사) + 얼굴 인식(person_id) → Gemini(화면해설) → TTS → ffmpeg 합성 → MP4 출력
```

Whisper 분석과 얼굴 인식은 각각 별도 Celery 태스크로 병렬 실행되고,
둘 다 COMPLETED 되면 Gemini 화면해설 생성 → TTS → ffmpeg 합성이 순서대로 진행됩니다.

### Gemini 화면해설 생성 (`pipeline/narrator.py`)

- `narration_safe`(대사 없음 + 3초 이상) 구간마다 `face_segments.json`에서 그 구간에 해당하는 프레임을 최대 `NARRATION_FRAMES_PER_SEGMENT`(기본 5장) 골라 보냅니다.
- 지금까지 나온 전체 대사(`segments.json`의 `speech=true` 텍스트)와 구간 직후 이어지는 대사를 프롬프트에 함께 넣어, 줄거리·인물 관계에 맞는 화면해설이 나오도록 합니다.
- 결과는 각 세그먼트의 `narration` 필드에 채워집니다.

### TTS (`pipeline/tts.py`)

- `edge-tts`(무료, API 키 불필요)로 `narration` 텍스트를 한국어 음성(`TTS_VOICE`, 기본 `ko-KR-SunHiNeural`)으로 변환해 `narration_audio/seg_{start}.mp3`에 저장합니다.

### 최종 합성 (`pipeline/synthesizer.py`)

- 원본 영상 + 원본(또는 무음) 오디오 + 구간별 화면해설 음성을 ffmpeg로 합성해 `uploads/{job_id}/output.mp4`를 만듭니다.
- 화면해설 음성이 침묵 구간보다 길면 `atempo`로 살짝 빠르게 읽어 구간 안에 맞춥니다(최대 1.6배속).
- `GET /api/jobs/{job_id}/download`로 완성된 영상을 받을 수 있고, 프론트엔드 결과 화면에서도 바로 재생·다운로드할 수 있습니다.
