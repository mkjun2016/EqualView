const BASE = '/api'

export async function uploadVideo(file, onProgress) {
  const formData = new FormData()
  formData.append('file', file)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/upload`)

    xhr.upload.addEventListener('progress', (e) => {
      if (e.lengthComputable) onProgress?.(Math.round((e.loaded / e.total) * 100))
    })

    xhr.addEventListener('load', () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText))
      } else {
        reject(new Error(`업로드 실패: ${xhr.status}`))
      }
    })

    xhr.addEventListener('error', () => reject(new Error('네트워크 오류')))
    xhr.send(formData)
  })
}

export async function getJobStatus(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`)
  if (!res.ok) throw new Error('상태 조회 실패')
  return res.json()
}

export function getDownloadUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download`
}
