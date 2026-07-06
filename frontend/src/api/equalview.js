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

export function getFrameUrl(jobId, frame) {
  const path = frame?.path || ''
  const filename = path.split('/').pop()
  if (!jobId || !filename) return null
  return `${BASE}/jobs/${jobId}/frames/${encodeURIComponent(filename)}`
}

export function collectPreviewFrames(enrichedResult) {
  const previews = []

  for (const segment of enrichedResult?.segments ?? []) {
    for (const frame of segment.frames ?? []) {
      if (!frame?.path) continue

      previews.push({
        ...frame,
        segmentId: segment.segment_id,
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

export function isFrameStatusTerminal(frameStatus) {
  return frameStatus === 'COMPLETED' || frameStatus === 'FAILED'
}

export function isJobAnalysisComplete(job) {
  return job?.status === 'COMPLETED' && isFrameStatusTerminal(job?.frame_status)
}

export const JOB_POLL_DELAYS_MS = [2000, 3000, 5000]

export function createJobPollSnapshot(job) {
  return JSON.stringify({
    status: job?.status ?? null,
    progress: job?.progress ?? 0,
    current_step: job?.current_step ?? null,
    frame_status: job?.frame_status ?? null,
    frame_progress: job?.frame_progress ?? 0,
    frame_current_step: job?.frame_current_step ?? null,
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

export function deriveOverallProgress(job) {
  const speechProgress = job?.progress ?? 0
  const frameProgress = job?.frame_progress ?? 0

  if (job?.status !== 'COMPLETED') {
    return Math.round(speechProgress * 0.5)
  }

  if (isFrameStatusTerminal(job?.frame_status)) {
    return 100
  }

  return Math.round(50 + frameProgress * 0.5)
}

export function deriveProcessingSteps(job) {
  const titles = [
    'Extracting Audio',
    'Extracting Frames',
    'Building Output',
    'Ready',
  ]

  const status = job?.status ?? 'PENDING'
  const progress = job?.progress ?? 0
  const frameStatus = job?.frame_status ?? 'PENDING'

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

  let frameState = 'waiting'
  if (frameStatus === 'COMPLETED') frameState = 'completed'
  else if (frameStatus === 'FAILED') frameState = 'failed'
  else if (frameStatus === 'PROCESSING') frameState = 'in-progress'

  let outputState = 'waiting'
  if (isJobAnalysisComplete(job)) outputState = 'completed'
  else if (status === 'COMPLETED') outputState = 'in-progress'

  const readyState = isJobAnalysisComplete(job) ? 'completed' : 'waiting'

  return [
    { title: titles[0], state: audioState },
    { title: titles[1], state: frameState },
    { title: titles[2], state: outputState },
    { title: titles[3], state: readyState },
  ]
}

export function formatJobStatusMessage(job) {
  const parts = []

  if (job?.current_step) {
    parts.push(`${job.current_step} (${job.progress ?? 0}%)`)
  }

  if (job?.frame_current_step && job?.frame_status === 'PROCESSING') {
    parts.push(`${job.frame_current_step} (${job.frame_progress ?? 0}%)`)
  }

  if (job?.frame_status === 'FAILED' && job?.frame_error) {
    parts.push(`Frame: ${job.frame_error}`)
  }

  return parts.join(' · ')
}

export const INITIAL_PROCESSING_STEPS = [
  { title: 'Extracting Audio', state: 'in-progress' },
  { title: 'Extracting Frames', state: 'waiting' },
  { title: 'Building Output', state: 'waiting' },
  { title: 'Ready', state: 'waiting' },
]
