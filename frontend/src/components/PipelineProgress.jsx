import styles from './PipelineProgress.module.css'

const STEPS = [
  { key: 'uploading',  label: '영상 업로드' },
  { key: 'whisper',    label: '대사 분석 · 침묵 구간 감지' },
  { key: 'frames',     label: '핵심 프레임 추출' },
  { key: 'gemini',     label: '장면 분석 · 해설 생성' },
  { key: 'tts',        label: '해설 음성 변환' },
  { key: 'synthesis',  label: '오디오 합성 · 최종 출력' },
]

const STATUS_MAP = {
  pending:    { icon: '○', cls: 'pending' },
  processing: { icon: '◉', cls: 'processing' },
  done:       { icon: '●', cls: 'done' },
  error:      { icon: '✕', cls: 'error' },
}

export default function PipelineProgress({ status, uploadProgress, currentStep }) {
  function getStepStatus(key) {
    const idx = STEPS.findIndex((s) => s.key === key)
    const cur = STEPS.findIndex((s) => s.key === currentStep)
    if (status === 'error' && idx === cur) return 'error'
    if (idx < cur) return 'done'
    if (idx === cur) return 'processing'
    return 'pending'
  }

  return (
    <div className={styles.wrapper}>
      {status === 'uploading' && (
        <div className={styles.uploadBar}>
          <div className={styles.uploadLabel}>
            <span>업로드 중...</span>
            <span>{uploadProgress}%</span>
          </div>
          <div className={styles.track}>
            <div className={styles.fill} style={{ width: `${uploadProgress}%` }} />
          </div>
        </div>
      )}

      {status !== 'uploading' && (
        <ol className={styles.steps}>
          {STEPS.map((step) => {
            const s = getStepStatus(step.key)
            const { icon, cls } = STATUS_MAP[s]
            return (
              <li key={step.key} className={`${styles.step} ${styles[cls]}`}>
                <span className={styles.stepIcon}>{icon}</span>
                <span className={styles.stepLabel}>{step.label}</span>
                {s === 'processing' && <span className={styles.spinner} />}
              </li>
            )
          })}
        </ol>
      )}
    </div>
  )
}
