import { useState, useEffect, useRef } from 'react'
import UploadSection from './components/UploadSection'
import PipelineProgress from './components/PipelineProgress'
import ResultSection from './components/ResultSection'
import { uploadVideo, getJobStatus } from './api/equalview'
import styles from './App.module.css'

const POLL_INTERVAL = 2000

export default function App() {
  const [phase, setPhase] = useState('idle')        // idle | uploading | processing | done | error
  const [uploadProgress, setUploadProgress] = useState(0)
  const [currentStep, setCurrentStep] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [filename, setFilename] = useState('')
  const [errorMsg, setErrorMsg] = useState('')
  const pollRef = useRef(null)

  useEffect(() => {
    return () => clearInterval(pollRef.current)
  }, [])

  async function handleUpload(file) {
    setFilename(file.name)
    setPhase('uploading')
    setUploadProgress(0)

    try {
      const { job_id } = await uploadVideo(file, setUploadProgress)
      setJobId(job_id)
      setPhase('processing')
      setCurrentStep('whisper')
      startPolling(job_id)
    } catch (e) {
      setErrorMsg(e.message)
      setPhase('error')
    }
  }

  function startPolling(id) {
    pollRef.current = setInterval(async () => {
      try {
        const data = await getJobStatus(id)
        setCurrentStep(data.current_step)

        if (data.status === 'done') {
          clearInterval(pollRef.current)
          setPhase('done')
        } else if (data.status === 'error') {
          clearInterval(pollRef.current)
          setErrorMsg(data.error ?? '처리 중 오류가 발생했습니다.')
          setPhase('error')
        }
      } catch (e) {
        clearInterval(pollRef.current)
        setErrorMsg(e.message)
        setPhase('error')
      }
    }, POLL_INTERVAL)
  }

  function reset() {
    clearInterval(pollRef.current)
    setPhase('idle')
    setUploadProgress(0)
    setCurrentStep(null)
    setJobId(null)
    setFilename('')
    setErrorMsg('')
  }

  return (
    <div className={styles.layout}>
      <header className={styles.header}>
        <h1 className={styles.logo}>EqualView</h1>
        <p className={styles.tagline}>AI 화면해설 자동생성 서비스</p>
      </header>

      <main className={styles.card}>
        {phase === 'idle' && (
          <UploadSection onUpload={handleUpload} />
        )}

        {(phase === 'uploading' || phase === 'processing') && (
          <PipelineProgress
            status={phase}
            uploadProgress={uploadProgress}
            currentStep={currentStep}
          />
        )}

        {phase === 'done' && (
          <ResultSection jobId={jobId} filename={filename} onReset={reset} />
        )}

        {phase === 'error' && (
          <div className={styles.errorBox}>
            <p className={styles.errorTitle}>오류가 발생했습니다</p>
            <p className={styles.errorMsg}>{errorMsg}</p>
            <button className={styles.retryBtn} onClick={reset}>처음으로</button>
          </div>
        )}
      </main>
    </div>
  )
}
