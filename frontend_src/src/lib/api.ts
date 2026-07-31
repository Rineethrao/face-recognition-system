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
  department?: string
  role?: string
  embedding_count: number
  registered_at: string
  face_images: string[]
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

export async function getRecognitions(limit: number = 20): Promise<RecognitionEvent[]> {
  const response = await apiClient.get(`/recognitions?limit=${limit}`)
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
