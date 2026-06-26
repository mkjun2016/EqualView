import { useRef, useState } from 'react'
import styles from './UploadSection.module.css'

const ACCEPTED = ['video/mp4', 'video/quicktime', 'video/x-matroska', 'video/avi']
const MAX_SIZE_GB = 2

export default function UploadSection({ onUpload }) {
  const inputRef = useRef(null)
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState('')

  function validate(file) {
    if (!ACCEPTED.includes(file.type)) {
      return 'MP4, MOV, MKV, AVI 형식만 지원합니다.'
    }
    if (file.size > MAX_SIZE_GB * 1024 ** 3) {
      return `파일 크기는 ${MAX_SIZE_GB}GB 이하여야 합니다.`
    }
    return null
  }

  function handleFile(file) {
    const err = validate(file)
    if (err) { setError(err); return }
    setError('')
    onUpload(file)
  }

  function onDrop(e) {
    e.preventDefault()
    setDragging(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  function onInputChange(e) {
    const file = e.target.files[0]
    if (file) handleFile(file)
  }

  return (
    <div className={styles.wrapper}>
      <div
        className={`${styles.dropzone} ${dragging ? styles.dragging : ''}`}
        onClick={() => inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <div className={styles.icon}>🎬</div>
        <p className={styles.primary}>영상을 드래그하거나 클릭해서 업로드</p>
        <p className={styles.secondary}>MP4, MOV, MKV, AVI · 최대 2GB</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED.join(',')}
          onChange={onInputChange}
          hidden
        />
      </div>
      {error && <p className={styles.error}>{error}</p>}
    </div>
  )
}
