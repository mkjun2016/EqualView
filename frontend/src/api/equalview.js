const BASE = '/api'

export async function createJob(file) {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${BASE}/jobs`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) {
    throw new Error(`Job creation failed: ${res.status}`)
  }

  return res.json()
}

export async function getJobStatus(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}`)
  if (!res.ok) throw new Error('Failed to fetch job status')
  return res.json()
}

export async function getJobSegments(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}/segments`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Failed to fetch segments')
  }
  return res.json()
}

export async function getJobSegmentsEnriched(jobId) {
  const res = await fetch(`${BASE}/jobs/${jobId}/segments/enriched`)
  if (!res.ok) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Failed to fetch enriched segments')
  }
  return res.json()
}

export function getAnnotatedFrameUrl(jobId, frame) {
  const path = frame?.annotated_path || frame?.path || ''
  const filename = path.split('/').pop()
  if (!jobId || !filename) return null
  return `${BASE}/jobs/${jobId}/frames/${encodeURIComponent(filename)}`
}

export function collectPreviewFrames(enrichedResult) {
  const previews = []

  for (const segment of enrichedResult?.segments ?? []) {
    for (const frame of segment.frames ?? []) {
      if (!frame?.annotated_path && !frame?.path) continue

      previews.push({
        ...frame,
        segmentId: segment.segment_id,
        personIds: (frame.faces ?? [])
          .map((face) => face.person_id)
          .filter(Boolean),
      })
    }
  }

  return previews.sort((a, b) => a.timestamp - b.timestamp)
}

export async function sendVoiceCommand(audioBlob) {
  const formData = new FormData()
  formData.append('audio', audioBlob, 'voice.webm')

  const res = await fetch(`${BASE}/voice-command`, {
    method: 'POST',
    body: formData,
  })

  if (!res.ok) throw new Error('Voice command failed')
  return res.json()
}

export function isFaceStatusTerminal(faceStatus) {
  return faceStatus === 'COMPLETED' || faceStatus === 'FAILED'
}

export function isJobAnalysisComplete(job) {
  return (
    job?.status === 'COMPLETED' &&
    isFaceStatusTerminal(job?.face_status)
  )
}

export function deriveOverallProgress(job) {
  const speechProgress = job?.progress ?? 0
  const faceProgress = job?.face_progress ?? 0

  if (job?.status !== 'COMPLETED') {
    return Math.round(speechProgress * 0.5)
  }

  if (job?.face_status === 'COMPLETED' || job?.face_status === 'FAILED') {
    return 100
  }

  return Math.round(50 + faceProgress * 0.5)
}

export function deriveProcessingSteps(job) {
  const titles = [
    'Extracting Audio',
    'Detecting Faces',
    'Merging Segments',
    'Ready',
  ]

  const status = job?.status ?? 'PENDING'
  const progress = job?.progress ?? 0
  const faceStatus = job?.face_status ?? 'PENDING'

  if (status === 'FAILED') {
    return titles.map((title, index) => ({
      title,
      state: index === 0 ? 'failed' : 'waiting',
    }))
  }

  const audioState =
    status === 'COMPLETED'
      ? 'completed'
      : progress > 0
        ? 'in-progress'
        : 'waiting'

  let faceState = 'waiting'
  if (faceStatus === 'COMPLETED') faceState = 'completed'
  else if (faceStatus === 'FAILED') faceState = 'failed'
  else if (faceStatus === 'PROCESSING') faceState = 'in-progress'
  else if (status === 'COMPLETED') faceState = 'in-progress'

  let mergeState = 'waiting'
  if (isJobAnalysisComplete(job)) mergeState = 'completed'
  else if (status === 'COMPLETED' && faceStatus === 'PROCESSING') {
    mergeState = 'in-progress'
  }

  const readyState = isJobAnalysisComplete(job) ? 'completed' : 'waiting'

  return [
    { title: titles[0], state: audioState },
    { title: titles[1], state: faceState },
    { title: titles[2], state: mergeState },
    { title: titles[3], state: readyState },
  ]
}

export function formatJobStatusMessage(job) {
  const parts = []

  if (job?.current_step) {
    parts.push(`${job.current_step} (${job.progress ?? 0}%)`)
  }

  if (job?.face_current_step && job?.face_status === 'PROCESSING') {
    parts.push(`${job.face_current_step} (${job.face_progress ?? 0}%)`)
  }

  if (job?.face_status === 'FAILED' && job?.face_error) {
    parts.push(`Face: ${job.face_error}`)
  }

  return parts.join(' · ')
}

export const INITIAL_PROCESSING_STEPS = [
  { title: 'Extracting Audio', state: 'in-progress' },
  { title: 'Detecting Faces', state: 'waiting' },
  { title: 'Merging Segments', state: 'waiting' },
  { title: 'Ready', state: 'waiting' },
]
