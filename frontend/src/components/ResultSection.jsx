import { getDownloadUrl } from '../api/equalview'
import styles from './ResultSection.module.css'

export default function ResultSection({ jobId, filename, onReset }) {
  return (
    <div className={styles.wrapper}>
      <div className={styles.badge}>완료</div>
      <h2 className={styles.title}>화면해설 음성 삽입 완료</h2>
      <p className={styles.sub}>{filename} 처리가 끝났습니다.</p>

      <a
        className={styles.downloadBtn}
        href={getDownloadUrl(jobId)}
        download
      >
        결과 영상 다운로드
      </a>

      <button className={styles.resetBtn} onClick={onReset}>
        다른 영상 처리하기
      </button>
    </div>
  )
}
