import axios from 'axios'

export interface HealthData {
  status: string
  database?: {
    total_persons: number
  }
  faiss?: {
    total_registered_vectors: number
    is_loaded: boolean
  }
  system?: {
    cpu_percent: number
    ram_percent: number
    gpu_percent: number
  }
}

export interface CameraConfig {
  id: string
  camera_id: string
  name: string
  source: string
  location: string
  enabled: boolean
  rotation: number
  fps_limit: number
  status?: string
  last_heartbeat?: string
  error_count?: number
  description?: string
  brand?: string
  ip_address?: string
  port?: number
  username?: string
  password?: string
  channel?: number
  stream_type?: string
  last_recognition?: {
    name: string
    recognized_at: string
  }
}

export interface RecognitionEvent {
  id: number
  person_id: string
  name: string
  similarity: number
  track_id: any
  camera_id: string
  embedding_version?: number
  quality_score?: number
  recognized_at: string
  face_snapshot_url?: string
}

export interface RecognitionPersonSummary {
  person_id: string
  name: string
  total_count: number
  avg_confidence: number
  last_seen_time: string
  last_seen_camera: string
}

export interface DetectedFace {
  track_id: number
  crop_base64: string
  is_recognized: boolean
  name: string
  timestamp: string
}

export interface Person {
  person_id: string
  name: string
  first_name?: string
  last_name?: string
  department?: string
  role?: string
  phone?: string
  email?: string
  notes?: string
  embedding_count: number
  registered_at: string
  face_images: string[]
}

export interface PersonUpdatePayload {
  first_name?: string
  last_name?: string
  name?: string
  department?: string
  role?: string
  phone?: string
  email?: string
  notes?: string
}

const apiClient = axios.create({
  baseURL: '',
})

export async function getHealth(): Promise<HealthData> {
  const response = await apiClient.get('/health')
  return response.data.data
}

export async function getCameras(): Promise<CameraConfig[]> {
  const response = await apiClient.get('/cameras')
  return response.data.data
}

export async function getRecognitions(limit: number = 200, personId?: string): Promise<RecognitionEvent[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (personId) params.set('person_id', personId)
  const response = await apiClient.get(`/recognitions?${params.toString()}`)
  return response.data.data
}

export async function getRecognitionSummaries(search?: string): Promise<RecognitionPersonSummary[]> {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  const qs = params.toString()
  const response = await apiClient.get(`/recognitions/summary${qs ? `?${qs}` : ''}`)
  return response.data.data
}

export async function getDetectedFaces(): Promise<DetectedFace[]> {
  const response = await apiClient.get('/detected_faces')
  return response.data.data
}

export async function registerSnapshot(cropBase64: string, personId: string, name: string): Promise<any> {
  const response = await apiClient.post('/register/snapshot', {
    crop_base64: cropBase64,
    person_id: personId,
    name: name,
  })
  return response.data
}

export async function getPersons(): Promise<Person[]> {
  const response = await apiClient.get('/persons')
  return response.data.data
}

export async function deletePerson(personId: string): Promise<any> {
  const response = await apiClient.delete(`/persons/${encodeURIComponent(personId)}`)
  return response.data
}

export async function updatePerson(personId: string, payload: PersonUpdatePayload): Promise<any> {
  const response = await apiClient.put(`/persons/${encodeURIComponent(personId)}`, payload)
  return response.data
}

// ── Browser / Device Webcam Live Recognition ───────────────────────────────

export interface AnalyzedFace {
  bbox: number[]
  score: number
  person_id: string
  name: string
  similarity: number
  status: 'recognized' | 'unknown' | 'low_confidence' | 'no_landmarks'
  quality_ok?: boolean
  quality_reason?: string
}

export interface AnalyzeFrameResult {
  faces: AnalyzedFace[]
  frame_width: number
  frame_height: number
  camera_id: string
}

export async function analyzeFrame(imageBase64: string, cameraId = 'browser_cam'): Promise<AnalyzeFrameResult> {
  const response = await apiClient.post('/recognition/analyze_frame', {
    image_base64: imageBase64,
    camera_id: cameraId,
    log_events: true,
  })
  return response.data.data
}

// ── Reports & Analytics ─────────────────────────────────────────────────────

export interface ReportSummary {
  range: { start: string; end: string }
  total_events: number
  known_events: number
  unknown_events: number
  unique_persons_seen: number
  total_persons_registered: number
  by_camera: { camera_id: string; count: number }[]
  by_day: { date: string; count: number }[]
  top_persons: { person_id: string; name: string; count: number }[]
}

export interface ReportFilters {
  start_date?: string
  end_date?: string
  camera_id?: string
}

function buildQuery(filters: ReportFilters): string {
  const params = new URLSearchParams()
  if (filters.start_date) params.set('start_date', filters.start_date)
  if (filters.end_date) params.set('end_date', filters.end_date)
  if (filters.camera_id) params.set('camera_id', filters.camera_id)
  const qs = params.toString()
  return qs ? `?${qs}` : ''
}

export async function getReportSummary(filters: ReportFilters = {}): Promise<ReportSummary> {
  const response = await apiClient.get(`/reports/summary${buildQuery(filters)}`)
  return response.data.data
}

async function downloadFile(url: string, fallbackName: string) {
  const response = await apiClient.get(url, { responseType: 'blob' })
  const disposition: string = response.headers['content-disposition'] || ''
  const match = disposition.match(/filename=([^;]+)/)
  const filename = match ? match[1].trim() : fallbackName
  const blobUrl = window.URL.createObjectURL(new Blob([response.data]))
  const link = document.createElement('a')
  link.href = blobUrl
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.URL.revokeObjectURL(blobUrl)
}

export async function downloadReportCsv(filters: ReportFilters = {}): Promise<void> {
  await downloadFile(`/reports/export/csv${buildQuery(filters)}`, 'recognition_report.csv')
}

export async function downloadReportPdf(filters: ReportFilters = {}): Promise<void> {
  await downloadFile(`/reports/export/pdf${buildQuery(filters)}`, 'recognition_report.pdf')
}
