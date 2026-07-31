import axios from 'axios'

export interface CreatePersonPayload {
  person_id: string
  first_name: string
  last_name: string
  department?: string
  role?: string
  phone?: string
  email?: string
  notes?: string
  files: File[]
}

export interface DetectedFaceMetadata {
  track_id: number
  bbox: number[]
  blur_score: number
  crop_base64: string
  is_recognized?: boolean
  name?: string
  similarity?: number
}

const apiClient = axios.create({
  baseURL: '',
})

export async function createPerson(payload: CreatePersonPayload): Promise<any> {
  const formData = new FormData()
  formData.append('person_id', payload.person_id)
  formData.append('first_name', payload.first_name)
  formData.append('last_name', payload.last_name)
  if (payload.department) formData.append('department', payload.department)
  if (payload.role) formData.append('role', payload.role)
  if (payload.phone) formData.append('phone', payload.phone)
  if (payload.email) formData.append('email', payload.email)
  if (payload.notes) formData.append('notes', payload.notes)
  
  payload.files.forEach((file) => {
    formData.append('files', file)
  })

  const response = await apiClient.post('/register/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
  })
  return response.data
}

export async function getDetectedFacesMetadata(cameraId: string): Promise<DetectedFaceMetadata[]> {
  const res = await apiClient.get(`/cameras/${encodeURIComponent(cameraId)}/detected_faces`)
  return res.data.data
}
