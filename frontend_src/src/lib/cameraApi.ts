import axios from 'axios'
import type { CameraConfig } from './api'

export type { CameraConfig }

export interface CameraCreatePayload {
  id?: string
  camera_id?: string
  name: string
  location?: string
  description?: string
  brand: string
  ip_address?: string
  port?: number
  username?: string
  password?: string
  channel?: number
  stream_type?: string
  source?: string
  enabled: boolean
  rotation?: number
  fps_limit?: number
}

export interface CameraTestResult {
  connected: boolean
  elapsed_s: number
  resolution?: string
  preview_b64?: string
}

const apiClient = axios.create({
  baseURL: '',
})

export const api = apiClient

export async function getCameras(): Promise<CameraConfig[]> {
  const response = await apiClient.get('/cameras')
  return response.data.data
}

export async function getCamera(cameraId: string): Promise<CameraConfig> {
  const response = await apiClient.get(`/cameras/${encodeURIComponent(cameraId)}`)
  return response.data.data
}

export async function createCamera(payload: CameraCreatePayload): Promise<CameraConfig> {
  const response = await apiClient.post('/cameras', payload)
  return response.data.data
}

export async function updateCamera(cameraId: string, payload: CameraCreatePayload): Promise<CameraConfig> {
  const response = await apiClient.put(`/cameras/${encodeURIComponent(cameraId)}`, payload)
  return response.data.data
}

export async function deleteCamera(cameraId: string): Promise<any> {
  const response = await apiClient.delete(`/cameras/${encodeURIComponent(cameraId)}`)
  return response.data
}

export async function testCameraConnection(payload: any): Promise<CameraTestResult> {
  const response = await apiClient.post('/camera/test', payload)
  return response.data.data
}

export function getStreamUrl(cameraId: string): string {
  return `/video_feed/${encodeURIComponent(cameraId)}`
}
