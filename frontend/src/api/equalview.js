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

const PROCESSING_TITLES = [
  'Extracting Dialogue',
  'Detecting Faces',
  'Generating Narration',
  'Combining Audio',
]

function statusToStepState(status) {
  if (status === 'COMPLETED') return 'completed'
  if (status === 'FAILED') return 'failed'
  if (status === 'PROCESSING') return 'in-progress'
  return 'waiting'
}

export function deriveProcessingSteps(job) {
  return [
    {
      title: PROCESSING_TITLES[0],
      state: statusToStepState(job.status),
    },
    {
      title: PROCESSING_TITLES[1],
      state: statusToStepState(job.face_status),
    },
    {
      title: PROCESSING_TITLES[2],
      state: statusToStepState(job.narration_status),
    },
    {
      title: PROCESSING_TITLES[3],
      state: statusToStepState(job.combine_status),
    },
  ]
}

export function getProcessingProgress(steps) {
  const completedCount = steps.filter(
    (step) => step.state === 'completed'
  ).length

  return completedCount * (100 / PROCESSING_TITLES.length)
}

export function deriveProcessingStepsFromProgress(progress, status) {
  const titles = [
    'Extracting Audio and Frames',
    'Generating Narration',
    'Combining Audio',
  ]

  if (status === 'COMPLETED') {
    return titles.map((title) => ({ title, state: 'completed' }))
  }

  if (status === 'FAILED') {
    return titles.map((title, index) => ({
      title,
      state: index === 0 ? 'failed' : 'waiting',
    }))
  }

  const thresholds = [
    { start: 0, done: 30 },
    { start: 30, done: 60 },
    { start: 60, done: 80 },
    { start: 80, done: 100 },
  ]

  return titles.map((title, index) => {
    const { start, done } = thresholds[index]
    let state = 'waiting'

    if (progress >= done) state = 'completed'
    else if (progress >= start) state = 'in-progress'

    return { title, state }
  })
}

export const INITIAL_PROCESSING_STEPS = [
  { title: 'Extracting Dialogue', state: 'in-progress' },
  { title: 'Detecting Faces', state: 'in-progress' },
  { title: 'Generating Narration', state: 'waiting' },
  { title: 'Combining Audio', state: 'waiting' },
]
