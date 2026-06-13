# EqualView

시각장애인을 위한 AI 화면해설 자동생성 서비스.
영화 영상을 입력받아 대사가 없는 침묵 구간을 감지하고, AI가 생성한 한국어 화면해설 음성을 삽입해 합성된 결과물을 출력합니다.

---

## 파이프라인

```
영상 업로드
    ↓
Whisper — 대사 타임라인 추출 + 침묵 구간 감지
    ↓
침묵 구간에서 핵심 프레임 추출
    ↓
Gemini 1.5 Pro — 장면 분석 + 한국어 해설 생성
    ↓
TTS — 해설 텍스트 → 음성 변환
    ↓
ffmpeg — 원본 오디오 + 해설 음성 합성 → 최종 출력
```

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| 백엔드 | Python, FastAPI |
| AI | OpenAI Whisper, Gemini 1.5 Pro, TTS API |
| 영상/오디오 처리 | ffmpeg, pydub |
| 프론트엔드 | React |

---

## 폴더 구조

```
equalview/
├── backend/
│   ├── api/          # FastAPI 라우터, 엔드포인트
│   ├── pipeline/     # 파이프라인 단계별 모듈 (Whisper, Gemini, TTS, 합성)
│   └── utils/        # 공통 유틸리티
└── frontend/
    └── src/
        ├── components/   # UI 컴포넌트
        └── api/          # 백엔드 API 호출 모듈
```

---

## 로컬 개발 환경 세팅

> 세팅 방법은 개발이 진행되면 업데이트 예정입니다.

### 요구사항

- Python 3.10+
- Node.js 18+
- ffmpeg

### 백엔드

```bash
cd equalview/backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn api.main:app --reload
```

### 프론트엔드

```bash
cd equalview/frontend
npm install
npm run dev
```

---

## 환경 변수

`.env` 파일을 `equalview/backend/` 에 생성 후 아래 항목을 채워주세요.

```
GEMINI_API_KEY=your_gemini_api_key
TTS_API_KEY=your_tts_api_key
```
