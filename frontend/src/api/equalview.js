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

export function deriveProcessingSteps(progress, status) {
  const titles = [
    'Extracting Audio',
    'Analyzing Scenes',
    'Generating Narration',
    'Preparing Output',
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
  { title: 'Extracting Audio', state: 'in-progress' },
  { title: 'Analyzing Scenes', state: 'waiting' },
  { title: 'Generating Narration', state: 'waiting' },
  { title: 'Preparing Output', state: 'waiting' },
]
