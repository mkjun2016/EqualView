# EqualView — AGENTS.md

시각장애인을 위한 AI 화면해설 자동생성 서비스.
영화 영상을 입력받아 대사 없는 침묵 구간에 AI 생성 한국어 화면해설 음성을 삽입한다.

---

## 프로젝트 구조

```
EqualView/
├── backend/
│   ├── api/          # FastAPI 라우터, 엔드포인트
│   ├── pipeline/     # 파이프라인 단계별 모듈
│   └── utils/        # 공통 유틸리티
└── frontend/
    ├── index.html
    ├── vite.config.js
    └── src/
        ├── App.jsx             # 최상위 컴포넌트, 전체 phase 상태 관리
        ├── App.module.css
        ├── index.css           # 전역 CSS 변수 (다크 테마)
        ├── main.jsx
        ├── api/
        │   └── equalview.js    # 백엔드 API 호출 모듈
        └── components/
            ├── UploadSection   # 드래그&드롭 영상 업로드
            ├── PipelineProgress # 6단계 파이프라인 진행 표시
            └── ResultSection   # 완료 후 다운로드
```

---

## 파이프라인

```
영상 업로드
    ↓  (step: uploading)
Whisper — 대사 타임라인 추출 + 침묵 구간 감지
    ↓  (step: whisper)
핵심 프레임 추출
    ↓  (step: frames)
Gemini 1.5 Pro — 장면 분석 + 한국어 해설 생성
    ↓  (step: gemini)
TTS — 해설 텍스트 → 음성 변환
    ↓  (step: tts)
ffmpeg — 원본 오디오 + 해설 음성 합성 → 최종 출력
    ↓  (step: synthesis)
완료
```

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 백엔드 | Python, FastAPI |
| AI | OpenAI Whisper, Gemini 1.5 Pro, TTS API |
| 영상/오디오 처리 | ffmpeg, pydub |
| 프론트엔드 | React 18, Vite 5 |

---

## 프론트엔드

### Phase 상태 머신 (`App.jsx`)

```
idle → uploading → processing → done
                              ↘ error
```

- `idle`: 업로드 화면
- `uploading`: 파일 전송 중 (진행률 표시)
- `processing`: 백엔드 파이프라인 실행 중 (2초 폴링)
- `done`: 다운로드 화면
- `error`: 오류 메시지 + 처음으로 버튼

### API 모듈 (`src/api/equalview.js`)

| 함수 | 설명 |
|------|------|
| `uploadVideo(file, onProgress)` | `POST /api/upload` — `{ job_id }` 반환 |
| `getJobStatus(jobId)` | `GET /api/jobs/:id` — `{ status, current_step, error }` 반환 |
| `getDownloadUrl(jobId)` | `GET /api/jobs/:id/download` URL 반환 |

Vite 개발 서버에서 `/api` 요청은 `http://localhost:8000`으로 프록시된다 (`vite.config.js`).

### 스타일

- CSS Modules 사용 (전역 클래스 충돌 없음)
- 다크 테마 전용, CSS 변수는 `src/index.css`의 `:root`에 정의

```css
--bg, --surface, --surface-2, --border
--accent, --accent-hover
--text, --text-muted
--success, --error, --warning
```

---

## 백엔드 API 명세 (프론트엔드 기준)

백엔드가 아래 인터페이스를 맞춰야 프론트엔드와 연결된다.

### `POST /api/upload`
- Body: `multipart/form-data`, 필드명 `file`
- Response: `{ "job_id": "<string>" }`

### `GET /api/jobs/{job_id}`
- Response:
```json
{
  "status": "processing" | "done" | "error",
  "current_step": "whisper" | "frames" | "gemini" | "tts" | "synthesis",
  "error": "<string | null>"
}
```

### `GET /api/jobs/{job_id}/download`
- Response: 처리된 영상 파일 스트리밍

---

## 환경 변수

`backend/.env` 파일에 작성:

```
GEMINI_API_KEY=
TTS_API_KEY=
```

---

## 개발 서버 실행

```bash
# 프론트엔드
cd frontend
npm install
npm run dev       # http://localhost:5173

# 백엔드 (세팅 후)
cd backend
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn api.main:app --reload   # http://localhost:8000
```
