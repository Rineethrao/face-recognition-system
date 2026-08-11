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
  first_seen_time?: string
  first_seen_camera?: string
  total_duration_seconds?: number
  total_duration?: string
  visit_count?: number
  is_currently_present?: boolean
  status?: string
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

export interface RecognitionDateItem {
  date_key: string
  date_formatted: string
  count: number
  is_today?: boolean
}

const apiClient = axios.create({
  baseURL: '/api',
})

export async function getHealth(): Promise<HealthData> {
  const response = await apiClient.get('/health')
  return response.data.data
}

export async function getCameras(): Promise<CameraConfig[]> {
  const response = await apiClient.get('/cameras')
  return response.data.data
}

export async function getRecognitionDates(): Promise<RecognitionDateItem[]> {
  const response = await apiClient.get('/recognitions/dates')
  return response.data.data || []
}

export async function getRecognitions(
  limit: number = 200,
  personId?: string,
  dateKey?: string,
  category?: string
): Promise<RecognitionEvent[]> {
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (personId) params.set('person_id', personId)
  if (dateKey && dateKey !== 'all') params.set('date_key', dateKey)
  if (category && category !== 'all') params.set('category', category)
  const response = await apiClient.get(`/recognitions?${params.toString()}`)
  return response.data.data
}

export async function getRecognitionSummaries(
  search?: string,
  dateKey?: string,
  category?: string
): Promise<RecognitionPersonSummary[]> {
  const params = new URLSearchParams()
  if (search) params.set('search', search)
  if (dateKey && dateKey !== 'all') params.set('date_key', dateKey)
  if (category && category !== 'all') params.set('category', category)
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

// ── Visitor Re-ID Subsystem API ──────────────────────────────────────────────
export interface VisitorItem {
  id: number
  visitor_code: string
  date_key: string
  first_seen_at: string
  last_seen_at: string
  first_camera_id: string
  last_camera_id: string
  sighting_count: number
  status: string
  promoted_person_id?: string
  primary_snapshot_url?: string
}

export interface VisitorDateItem {
  date_key: string
  date_formatted: string
  count: number
  is_today: boolean
}

export interface VisitorSighting {
  id: number
  camera_id: string
  camera_name: string
  track_id: string
  entered_at: string
  last_seen_at: string
  duration_formatted: string
  best_similarity: number
  second_best_similarity: number
  match_margin: number
  identity_confidence: number
  snapshot_url?: string
  metadata?: any
}

export interface VisitorTimelineResponse {
  visitor_code: string
  date_key: string
  first_seen_at: string
  last_seen_at: string
  status: string
  primary_snapshot_url?: string
  sightings: VisitorSighting[]
}

export interface VisitorStats {
  date_key: string
  total_visitors_today: number
  active_visitors: number
  promoted_visitors: number
  online_cameras: number
  total_sightings: number
}

export async function getVisitorDates(): Promise<VisitorDateItem[]> {
  const res = await apiClient.get('/visitors/dates')
  return res.data.data
}

export async function getVisitors(params: { date_key?: string; camera_id?: string; status?: string; search?: string } = {}): Promise<{ total: number; visitors: VisitorItem[] }> {
  const q = new URLSearchParams()
  if (params.date_key) q.set('date_key', params.date_key)
  if (params.camera_id) q.set('camera_id', params.camera_id)
  if (params.status) q.set('status', params.status)
  if (params.search) q.set('search', params.search)
  const res = await apiClient.get(`/visitors?${q.toString()}`)
  return res.data.data
}

export async function getVisitorStats(date_key?: string): Promise<VisitorStats> {
  const url = date_key ? `/visitors/stats?date_key=${date_key}` : '/visitors/stats'
  const res = await apiClient.get(url)
  return res.data.data
}

export async function getVisitorTimeline(visitorId: number, dateKey?: string): Promise<VisitorTimelineResponse> {
  const url = dateKey && dateKey !== 'all' ? `/visitors/${visitorId}/timeline?date_key=${dateKey}` : `/visitors/${visitorId}/timeline`
  const res = await apiClient.get(url)
  return res.data.data
}

export async function promoteVisitor(visitorId: number, payload: {
  first_name: string
  last_name: string
  department?: string
  role?: string
  phone?: string
  email?: string
  notes?: string
}): Promise<any> {
  const res = await apiClient.post(`/visitors/${visitorId}/promote`, payload)
  return res.data
}

export interface VisitorSampleSnapshot {
  id: number
  camera_id: string
  timestamp: string
  quality_score: number
  yaw: number
  pitch: number
  blur_score: number
  snapshot_url?: string
}

export async function getVisitorSnapshots(visitorId: number, dateKey?: string): Promise<VisitorSampleSnapshot[]> {
  const url = dateKey && dateKey !== 'all' ? `/visitors/${visitorId}/snapshots?date_key=${dateKey}` : `/visitors/${visitorId}/snapshots`
  const res = await apiClient.get(url)
  return res.data.data
}


export async function deleteVisitor(visitorId: number): Promise<any> {
  const res = await apiClient.delete(`/visitors/${visitorId}`)
  return res.data
}

export async function purgeAllVisitors(): Promise<any> {
  const res = await apiClient.delete('/visitors/purge_all')
  return res.data
}

export async function downloadVisitorReportCsv(params: { date_key?: string; status?: string; camera_id?: string } = {}): Promise<void> {
  const q = new URLSearchParams()
  if (params.date_key) q.set('date_key', params.date_key)
  if (params.status) q.set('status', params.status)
  if (params.camera_id) q.set('camera_id', params.camera_id)
  await downloadFile(`/visitors/export/csv?${q.toString()}`, `visitor_report_${params.date_key || 'today'}.csv`)
}

export async function downloadVisitorReportPdf(params: { date_key?: string; status?: string; camera_id?: string } = {}): Promise<void> {
  const q = new URLSearchParams()
  if (params.date_key) q.set('date_key', params.date_key)
  if (params.status) q.set('status', params.status)
  if (params.camera_id) q.set('camera_id', params.camera_id)
  await downloadFile(`/visitors/export/pdf?${q.toString()}`, `visitor_report_${params.date_key || 'today'}.pdf`)
}



