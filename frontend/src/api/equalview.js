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

export function getDownloadUrl(jobId) {
  return `${BASE}/jobs/${jobId}/download`
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
          .map((face) => (typeof face === 'string' ? face : face?.person_id))
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

export const JOB_POLL_DELAYS_MS = [2000, 3000, 5000]

export function createJobPollSnapshot(job) {
  return JSON.stringify({
    status: job?.status ?? null,
    progress: job?.progress ?? 0,
    current_step: job?.current_step ?? null,
    face_status: job?.face_status ?? null,
    face_progress: job?.face_progress ?? 0,
    narration_status: job?.narration_status ?? null,
    combine_status: job?.combine_status ?? null,
  })
}

export function nextJobPollDelayIndex(currentIndex, previousSnapshot, nextSnapshot) {
  if (previousSnapshot === null || previousSnapshot !== nextSnapshot) {
    return 0
  }
  return Math.min(currentIndex + 1, JOB_POLL_DELAYS_MS.length - 1)
}

export function getJobPollDelayMs(delayIndex) {
  return JOB_POLL_DELAYS_MS[Math.min(delayIndex, JOB_POLL_DELAYS_MS.length - 1)]
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

const PROCESSING_TITLES = [
  'Extracting Dialogue',
  'Detecting Faces',
  'Generating Narration',
  'Combining Audio',
]

function statusToStepState(status) {
  if (status === 'COMPLETED' || status === 'PARTIAL') return 'completed'
  if (status === 'FAILED') return 'failed'
  if (status === 'PROCESSING') return 'in-progress'
  return 'waiting'
}

export function deriveProcessingSteps(job) {
  return [
    { title: PROCESSING_TITLES[0], state: statusToStepState(job.status) },
    { title: PROCESSING_TITLES[1], state: statusToStepState(job.face_status) },
    { title: PROCESSING_TITLES[2], state: statusToStepState(job.narration_status) },
    { title: PROCESSING_TITLES[3], state: statusToStepState(job.combine_status) },
  ]
}

export function getProcessingProgress(steps) {
  const completedCount = steps.filter((step) => step.state === 'completed').length
  return completedCount * (100 / PROCESSING_TITLES.length)
}

export const INITIAL_PROCESSING_STEPS = [
  { title: 'Extracting Dialogue', state: 'in-progress' },
  { title: 'Detecting Faces', state: 'in-progress' },
  { title: 'Generating Narration', state: 'waiting' },
  { title: 'Combining Audio', state: 'waiting' },
]
