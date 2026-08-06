import { useState, useEffect, useRef } from 'react'
import {
  User, Camera, Video, Sparkles, CheckCircle2, AlertCircle, AlertTriangle, Trash2, X,
  ArrowRight, ArrowLeft, ShieldCheck, Check, Cpu, Play, Eye, Upload, RefreshCw,
  Image as ImageIcon
} from 'lucide-react'
import { TopBar } from '../components/TopBar'
import { RegistrationWizardNav } from '../components/RegistrationWizardNav'
import { AiAssistantPanel } from '../components/AiAssistantPanel'
import { useNavigate } from 'react-router-dom'
import { api, getCameras, type CameraConfig } from '../lib/cameraApi'
import { toast } from '../components/ui/Toast'
import { formatLocalTime } from '../lib/datetime'
import clsx from 'clsx'

const ROLE_OPTIONS = [
  'Employee',
  'Visitor',
  'Security',
  'Contractor',
  'VIP',
  'Watchlist',
  'Blacklist',
  'Missing Person',
]

interface GallerySample {
  id: string
  pose_bin: string
  quality_score: number
  timestamp: string
  preview_url: string
  method: string
}

export function RegisterPerson() {
  const navigate = useNavigate()

  // Wizard Step State (1 to 5)
  const [currentStep, setCurrentStep] = useState<number>(1)

  // Step 1: Person Metadata
  const [personId, setPersonId] = useState<string>(`P_${Date.now().toString().slice(-5)}`)
  const [firstName, setFirstName] = useState<string>('')
  const [lastName, setLastName] = useState<string>('')
  const [employeeId, setEmployeeId] = useState<string>('')
  const [department, setDepartment] = useState<string>('')
  const [designation, setDesignation] = useState<string>('')
  const [role, setRole] = useState<string>('Employee')
  const [phone, setPhone] = useState<string>('')
  const [email, setEmail] = useState<string>('')
  const [notes, setNotes] = useState<string>('')
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})

  // Update Mode Selection
  const [registeredPersons, setRegisteredPersons] = useState<any[]>([])
  const [selectedExistingId, setSelectedExistingId] = useState<string>('')

  // Step 2: Capture Method ('WEBCAM' | 'CCTV' | 'UPLOAD')
  const [captureMethod, setCaptureMethod] = useState<'WEBCAM' | 'CCTV' | 'UPLOAD'>('WEBCAM')

  // Step 3: Stream & AI Assistant State
  const [isCapturing, setIsCapturing] = useState<boolean>(false)
  const [aiAssistant, setAiAssistant] = useState<{
    face_detected: boolean
    centered: boolean
    sharp: boolean
    lighting: boolean
    eyes_visible: boolean
    current_pose?: string
    guidance?: string
    status?: string
    quality_score?: number
  }>({
    face_detected: false,
    centered: false,
    sharp: false,
    lighting: false,
    eyes_visible: false,
    guidance: 'Position face inside the frame',
    status: 'Ready for capture'
  })

  // Webcam Stream References & Multi-Camera Fallbacks
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [webcamStream, setWebcamStream] = useState<MediaStream | null>(null)
  const [webcamError, setWebcamError] = useState<string | null>(null)
  const [videoDevices, setVideoDevices] = useState<MediaDeviceInfo[]>([])
  const [selectedDeviceId, setSelectedDeviceId] = useState<string>('')

  // CCTV Stream References & Face Selection State
  const [cameraList, setCameraList] = useState<CameraConfig[]>([])
  const [selectedCameraId, setSelectedCameraId] = useState<string>('')
  const [targetLocked, setTargetLocked] = useState<boolean>(false)
  const [cctvFaces, setCctvFaces] = useState<any[]>([])
  const [cctvStreamKey, setCctvStreamKey] = useState<number>(Date.now())
  const [cctvError, setCctvError] = useState<boolean>(false)
  const cctvImgRef = useRef<HTMLImageElement>(null)
  const [targetState, setTargetState] = useState<string>('WAITING_FOR_SELECTION')
  const [targetDetails, setTargetDetails] = useState<any>(null)
  const [imgLoaded, setImgLoaded] = useState<boolean>(false)
  const [targetSamples, setTargetSamples] = useState<number>(6)
  const [poseCoverage, setPoseCoverage] = useState<Record<string, boolean>>({})
  const [hoveredFaceId, setHoveredFaceId] = useState<string | null>(null)

  // Recalculate aspect-ratio coordinates dynamically on window resize
  useEffect(() => {
    const handleResize = () => setImgLoaded(prev => !prev)
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const getOverlayBboxStyle = (bbox: number[]) => {
    if (!cctvImgRef.current || !bbox || bbox.length !== 4) return {}
    const img = cctvImgRef.current
    const naturalWidth = img.naturalWidth
    const naturalHeight = img.naturalHeight
    const clientWidth = img.clientWidth
    const clientHeight = img.clientHeight

    if (!naturalWidth || !naturalHeight || !clientWidth || !clientHeight) return {}

    const imgRatio = naturalWidth / naturalHeight
    const clientRatio = clientWidth / clientHeight

    let visibleWidth = clientWidth
    let visibleHeight = clientHeight
    let offsetX = 0
    let offsetY = 0

    if (clientRatio > imgRatio) {
      visibleWidth = clientHeight * imgRatio
      offsetX = (clientWidth - visibleWidth) / 2
    } else {
      visibleHeight = clientWidth / imgRatio
      offsetY = (clientHeight - visibleHeight) / 2
    }

    const scaleX = visibleWidth / naturalWidth
    const scaleY = visibleHeight / naturalHeight

    const left = bbox[0] * scaleX + offsetX
    const top = bbox[1] * scaleY + offsetY
    const width = (bbox[2] - bbox[0]) * scaleX
    const height = (bbox[3] - bbox[1]) * scaleY

    return {
      position: 'absolute' as const,
      left: `${left}px`,
      top: `${top}px`,
      width: `${width}px`,
      height: `${height}px`
    }
  }

  /** Keep a single overlay box per physical face (IoU dedupe). */
  const dedupeFacesByIou = (faces: any[], iouThresh = 0.4) => {
    const bboxIou = (a: number[], b: number[]) => {
      if (!a || !b || a.length !== 4 || b.length !== 4) return 0
      const ix1 = Math.max(a[0], b[0])
      const iy1 = Math.max(a[1], b[1])
      const ix2 = Math.min(a[2], b[2])
      const iy2 = Math.min(a[3], b[3])
      const inter = Math.max(0, ix2 - ix1) * Math.max(0, iy2 - iy1)
      if (inter <= 0) return 0
      const areaA = Math.max(0, a[2] - a[0]) * Math.max(0, a[3] - a[1])
      const areaB = Math.max(0, b[2] - b[0]) * Math.max(0, b[3] - b[1])
      return inter / Math.max(areaA + areaB - inter, 1e-6)
    }

    const ranked = [...faces]
      .filter(f => f?.bbox?.length === 4)
      .sort((a, b) => {
        const score = (f: any) => {
          const [x1, y1, x2, y2] = f.bbox
          const area = Math.max(0, x2 - x1) * Math.max(0, y2 - y1)
          return (Number(f.confidence) || 0.5) * 2 + (Number(f.quality) || 0) + area / 10000
        }
        return score(b) - score(a)
      })

    const kept: any[] = []
    for (const face of ranked) {
      if (kept.some(k => bboxIou(face.bbox, k.bbox) >= iouThresh)) continue
      kept.push(face)
    }
    return kept
  }

  const selectedCam = cameraList.find(c => (c.id || c.camera_id) === selectedCameraId)
  const isSelectedCamOnline = selectedCam ? (selectedCam.enabled && selectedCam.status !== 'OFFLINE') : false

  // Lock selected FACE in CCTV mode (face-first, not Track ID)
  const handleSelectFace = async (face: any) => {
    if (targetLocked) return
    try {
      const res = await api.post('/register/session/select_face', {
        camera_id: selectedCameraId,
        detection_id: face.detection_id,
        bbox: face.bbox
      })
      if (res.data?.status === 'success') {
        setTargetLocked(true)
        setTargetState(res.data?.data?.state || 'TARGET_LOCKED')
        if (res.data?.data?.target) setTargetDetails(res.data.data.target)
        toast.success('Face selected', 'Target locked — automatic capture started')
      }
    } catch (err: any) {
      console.error('Failed to select face:', err)
      toast.error('Face select failed', err.response?.data?.detail || 'Try clicking the face again')
    }
  }

  const handleUnlockTarget = async () => {
    try {
      await api.post('/register/session/track_select', {
        track_id: -1,
        camera_id: selectedCameraId
      })
      setTargetLocked(false)
      setTargetState('WAITING_FOR_SELECTION')
      setTargetDetails(null)
    } catch (err) {
      console.error('Failed to unlock target:', err)
    }
  }

  const handleChangeTarget = async () => {
    if (gallery.length > 0) {
      const confirmRestart = window.confirm(
        "Changing the face may mix identities. Restart capture and clear already captured samples?"
      )
      if (!confirmRestart) return

      try {
        for (const sample of gallery) {
          await api.delete(`/register/session/sample/${sample.id}`)
        }
        setGallery([])
      } catch (err) {
        console.error("Failed to clear gallery samples:", err)
      }
    }
    await handleUnlockTarget()
  }

  // Gallery State (Step 4)
  const [gallery, setGallery] = useState<GallerySample[]>([])
  const [uploadingFiles, setUploadingFiles] = useState<boolean>(false)

  // Duplicate assessment (Step 4 warning — does not change commit hard-block)
  const [duplicateCheck, setDuplicateCheck] = useState<{
    level: 'none' | 'soft' | 'hard'
    matched_person_id?: string | null
    matched_name?: string | null
    similarity?: number
  } | null>(null)
  const [softContinueAck, setSoftContinueAck] = useState(false)
  const [duplicateChecking, setDuplicateChecking] = useState(false)

  // Step 5: Commit Processing State
  const [isProcessing, setIsProcessing] = useState<boolean>(false)
  const [processingStage, setProcessingStage] = useState<string>('Initializing...')
  const [registrationCompleted, setRegistrationCompleted] = useState<boolean>(false)
  const [commitError, setCommitError] = useState<string | null>(null)

  // Visual toast feedback on auto-captured sample
  const prevGalleryCount = useRef(0)
  useEffect(() => {
    if (gallery.length > prevGalleryCount.current && prevGalleryCount.current >= 0 && gallery.length > 0) {
      if (gallery.length > prevGalleryCount.current) {
        const latest = gallery[gallery.length - 1]
        toast.success(
          `Sample Captured (${gallery.length}/${targetSamples})`,
          `Pose: ${latest?.pose_bin || 'FACE'} • Quality Verified`
        )
      }
    }
    prevGalleryCount.current = gallery.length
  }, [gallery.length, targetSamples])

  const runDuplicateCheck = async () => {
    setDuplicateChecking(true)
    setSoftContinueAck(false)
    try {
      const res = await api.post('/register/session/check_duplicate')
      const data = res.data?.data
      if (data) {
        setDuplicateCheck({
          level: data.level || 'none',
          matched_person_id: data.matched_person_id,
          matched_name: data.matched_name,
          similarity: data.similarity,
        })
      } else {
        setDuplicateCheck({ level: 'none' })
      }
    } catch {
      setDuplicateCheck({ level: 'none' })
    } finally {
      setDuplicateChecking(false)
    }
  }

  // Assess duplicates whenever gallery review (Step 4) is shown or gallery changes
  useEffect(() => {
    if (currentStep !== 4) return
    runDuplicateCheck()
  }, [currentStep, gallery.length])

  const handleUpdateExistingFromWarning = async () => {
    const matchedId = duplicateCheck?.matched_person_id
    if (!matchedId) return

    try {
      await api.delete('/register/session')
    } catch {}

    const match = registeredPersons.find((p: any) => p.person_id === matchedId)
    setSelectedExistingId(matchedId)
    setPersonId(matchedId)
    if (match) {
      const parts = (match.name || '').split(' ')
      setFirstName(match.first_name || parts[0] || '')
      setLastName(match.last_name || parts.slice(1).join(' ') || '')
      setEmployeeId(match.person_id)
      setDepartment(match.department || '')
      setRole(match.role || 'Employee')
    } else {
      setFirstName(duplicateCheck?.matched_name?.split(' ')[0] || '')
      setLastName(duplicateCheck?.matched_name?.split(' ').slice(1).join(' ') || '')
      setEmployeeId(matchedId)
    }

    setGallery([])
    setDuplicateCheck(null)
    setSoftContinueAck(false)
    setIsCapturing(false)
    setTargetLocked(false)
    setCurrentStep(1)
    toast.info(
      'Update existing person',
      `Continue registration for ${duplicateCheck?.matched_name || matchedId} instead of creating a new profile.`
    )
  }

  // Load existing persons & CCTV cameras on mount
  useEffect(() => {
    api.get('/persons').then((res) => {
      if (res.data?.data) setRegisteredPersons(res.data.data)
    }).catch(() => {})

    getCameras().then((data) => {
      setCameraList(data)
      if (data.length > 0) {
        const active = data.find(c => c.enabled && c.status !== 'OFFLINE') || data[0]
        setSelectedCameraId(active.id || active.camera_id || '')
      }
    }).catch(() => {})
  }, [])

  // CCTV Polling Loop (Active during Step 3 CCTV mode)
  useEffect(() => {
    if (currentStep !== 3 || captureMethod !== 'CCTV') return

    setCctvError(false)
    let isMounted = true

    const pollDetectedFaces = async () => {
      try {
        const res = await api.get('/detected_faces')
        const faces = res.data?.data || []
        if (isMounted) {
          const filtered = faces.filter((f: any) => !f.camera_id || f.camera_id === selectedCameraId)
          setCctvFaces(dedupeFacesByIou(filtered, 0.4))
        }
      } catch (err) {}
    }

    const pollStatus = async () => {
      try {
        const res = await api.get('/register/status')
        const data = res.data?.data
        if (isMounted && data) {
          if (data.ai_assistant) setAiAssistant(data.ai_assistant)
          if (data.gallery) setGallery(data.gallery)
          if (typeof data.target_samples === 'number') setTargetSamples(data.target_samples)
          if (data.pose_coverage) setPoseCoverage(data.pose_coverage)
          if (typeof data.target_locked === 'boolean') {
            setTargetLocked(data.target_locked)
          } else if (data.state) {
            setTargetLocked(data.state !== 'WAITING_FOR_SELECTION' && data.state !== 'WAITING_FOR_TARGET')
          }
          if (data.state) setTargetState(data.state)
          if (data.target) setTargetDetails(data.target)
        }
      } catch (err) {}
    }

    pollDetectedFaces()
    pollStatus()

    const intervalFaces = setInterval(pollDetectedFaces, 400)
    const intervalStatus = setInterval(pollStatus, 500)

    return () => {
      isMounted = false
      clearInterval(intervalFaces)
      clearInterval(intervalStatus)
    }
  }, [currentStep, captureMethod, selectedCameraId])

  // Enumerate Video Devices
  const refreshVideoDevices = async () => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      const vDevs = devices.filter(d => d.kind === 'videoinput')
      setVideoDevices(vDevs)
      if (vDevs.length > 0 && !selectedDeviceId) {
        setSelectedDeviceId(vDevs[0].deviceId)
      }
    } catch (e) {}
  }

  // Manage Webcam stream lifetime with robust constraints fallback
  const startWebcam = async (deviceId?: string) => {
    setWebcamError(null)
    stopWebcam()

    const targetDeviceId = deviceId || selectedDeviceId
    const constraintList: MediaStreamConstraints[] = [
      targetDeviceId ? { video: { deviceId: { exact: targetDeviceId } } } : null,
      { video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' } },
      { video: { width: { ideal: 640 }, height: { ideal: 480 } } },
      { video: true }
    ].filter(Boolean) as MediaStreamConstraints[]

    let stream: MediaStream | null = null
    let lastError: any = null

    for (const constraints of constraintList) {
      try {
        stream = await navigator.mediaDevices.getUserMedia(constraints)
        if (stream) break
      } catch (err: any) {
        lastError = err
      }
    }

    if (!stream) {
      console.error('Webcam acquisition failed:', lastError)
      let msg = 'Unable to access webcam. Please check browser camera permissions.'
      if (lastError?.name === 'NotAllowedError' || lastError?.name === 'PermissionDeniedError') {
        msg = 'Camera access denied by browser. Click the camera icon in your browser address bar to grant permission.'
      } else if (lastError?.name === 'NotReadableError' || lastError?.name === 'TrackStartError') {
        msg = 'Webcam is currently in use by another app (Zoom, Teams, etc.). Please close other camera apps and click Retry.'
      } else if (lastError?.name === 'NotFoundError') {
        msg = 'No physical camera detected on your system.'
      }
      setWebcamError(msg)
      return
    }

    setWebcamStream(stream)
    if (videoRef.current) {
      videoRef.current.srcObject = stream
      videoRef.current.play().catch(() => {})
    }
    refreshVideoDevices()
  }

  const stopWebcam = () => {
    if (webcamStream) {
      webcamStream.getTracks().forEach((track) => track.stop())
      setWebcamStream(null)
    }
  }

  useEffect(() => {
    if (currentStep === 3 && captureMethod === 'WEBCAM') {
      startWebcam()
    } else {
      stopWebcam()
    }
    return () => stopWebcam()
  }, [currentStep, captureMethod, selectedDeviceId])

  // Step 3: Frame Evaluation Loop for Webcam Mode
  useEffect(() => {
    if (currentStep !== 3 || captureMethod !== 'WEBCAM' || !webcamStream) return

    let intervalId: any = null
    const evalFrame = async () => {
      const video = videoRef.current
      const canvas = canvasRef.current
      if (!video || !canvas || video.readyState < 2) return
      const vw = video.videoWidth || 640
      const vh = video.videoHeight || 480
      if (canvas.width !== vw) canvas.width = vw
      if (canvas.height !== vh) canvas.height = vh
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.drawImage(video, 0, 0, vw, vh)
      const b64 = canvas.toDataURL('image/jpeg', 0.8)

      try {
        const res = await api.post('/register/session/frame', {
          image_base64: b64,
          method: 'WEBCAM'
        })
        const data = res.data?.data
        if (data) {
          if (data.ai_assistant) setAiAssistant(data.ai_assistant)
          if (data.gallery) setGallery(data.gallery)
        }
      } catch (err) {}
    }

    intervalId = setInterval(evalFrame, 400)
    return () => clearInterval(intervalId)
  }, [currentStep, captureMethod, webcamStream])

  // Handle Photo File Uploads in Step 3
  const handleFileUpload = async (files: FileList | null) => {
    if (!files || files.length === 0) return
    setUploadingFiles(true)

    for (let i = 0; i < files.length; i++) {
      const file = files[i]
      const reader = new FileReader()
      await new Promise<void>((resolve) => {
        reader.onload = async (e) => {
          const b64 = e.target?.result as string
          if (b64) {
            try {
              const res = await api.post('/register/session/frame', {
                image_base64: b64,
                method: 'UPLOAD'
              })
              const data = res.data?.data
              if (data) {
                if (data.ai_assistant) setAiAssistant(data.ai_assistant)
                if (data.gallery) setGallery(data.gallery)
              }
            } catch (err) {}
          }
          resolve()
        }
        reader.readAsDataURL(file)
      })
    }
    setUploadingFiles(false)
  }

  // Handle Step 1 Validation & Proceed
  const handleStep1Submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const errors: Record<string, string> = {}
    if (!firstName.trim()) errors.firstName = 'First name is required'
    if (!lastName.trim()) errors.lastName = 'Last name is required'

    if (Object.keys(errors).length > 0) {
      setFormErrors(errors)
      return
    }

    setFormErrors({})
    const reqPersonId = employeeId.trim() || personId

    try {
      await api.post('/register/session/start', {
        person_id: reqPersonId,
        first_name: firstName.trim(),
        last_name: lastName.trim(),
        employee_id: employeeId.trim() || reqPersonId,
        department: department.trim(),
        designation: designation.trim(),
        role,
        phone: phone.trim(),
        email: email.trim(),
        notes: notes.trim()
      })
      setCurrentStep(2)
    } catch (err: any) {
      setFormErrors({ submit: err.response?.data?.detail || 'Failed to start session' })
    }
  }

  // Handle Step 4 -> Step 5 Final Commit
  const handleCommitRegistration = async () => {
    setCurrentStep(5)
    setIsProcessing(true)
    setCommitError(null)

    const stages = [
      'Aligning Facial Landmarks (5-Point Warp)...',
      'Generating 512-D ArcFace Identity Embeddings...',
      'Running Cross-Database Duplicate Identity Check...',
      'Writing Quality Gallery & Disk Snapshots...',
      'Updating In-Memory FAISS Vector Index...'
    ]

    for (let i = 0; i < stages.length; i++) {
      setProcessingStage(stages[i])
      await new Promise(r => setTimeout(r, 600))
    }

    try {
      const res = await api.post('/register/session/commit')
      if (res.data?.status === 'success') {
        setRegistrationCompleted(true)
      } else {
        setCommitError(res.data?.message || 'Registration failed')
      }
    } catch (err: any) {
      setCommitError(err.response?.data?.detail || err.message || 'Error committing registration')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleRemoveSample = async (sampleId: string) => {
    try {
      const res = await api.delete(`/register/session/sample/${sampleId}`)
      if (res.data?.data?.gallery) {
        setGallery(res.data.data.gallery)
      }
    } catch (err) {}
  }

  const canCommit =
    !duplicateChecking &&
    duplicateCheck?.level !== 'hard' &&
    (duplicateCheck?.level !== 'soft' || softContinueAck)

  return (
    <div className="flex flex-col h-full overflow-hidden bg-transparent text-slate-900 dark:text-slate-100 registration-form-page">
      <TopBar title="Enterprise Face Registration" />

      <main className="flex-1 overflow-y-auto max-w-7xl w-full mx-auto p-4 md:p-6 flex flex-col pb-10">
        {/* Wizard Step Progress Navigation */}
        <RegistrationWizardNav
          currentStep={currentStep}
          onStepClick={(s) => s < currentStep && setCurrentStep(s)}
        />

        {/* Hidden Canvas & File Inputs */}
        <canvas ref={canvasRef} className="hidden" />
        <input
          type="file"
          ref={fileInputRef}
          multiple
          accept="image/*"
          className="hidden"
          onChange={(e) => handleFileUpload(e.target.files)}
        />

        {/* STEP 1: PERSON INFORMATION */}
        {currentStep === 1 && (
          <div className="bg-slate-900/70 border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl backdrop-blur-xl max-w-4xl mx-auto w-full">
            <div className="flex items-center justify-between border-b border-slate-800 pb-5 mb-6">
              <div>
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <User className="w-5 h-5 text-blue-400" /> Step 1: Person Metadata & Profile
                </h2>
                <p className="text-xs text-slate-400 mt-1">Fill out employee information to initialize the registration gallery.</p>
              </div>

              {/* Selector for updating existing person */}
              {registeredPersons.length > 0 && (
                <div className="flex items-center gap-2 bg-slate-800/80 border border-slate-700 px-3 py-1.5 rounded-xl text-xs">
                  <span className="text-slate-400">Re-register / Edit:</span>
                  <select
                    value={selectedExistingId}
                    onChange={(e) => {
                      setSelectedExistingId(e.target.value)
                      const match = registeredPersons.find(p => p.person_id === e.target.value)
                      if (match) {
                        setPersonId(match.person_id)
                        const parts = (match.name || '').split(' ')
                        setFirstName(match.first_name || parts[0] || '')
                        setLastName(match.last_name || parts.slice(1).join(' ') || '')
                        setEmployeeId(match.person_id)
                        setDepartment(match.department || '')
                        setRole(match.role || 'Employee')
                      }
                    }}
                    className="bg-transparent text-slate-200 font-semibold focus:outline-none"
                  >
                    <option value="" className="bg-slate-900">New Profile</option>
                    {registeredPersons.map(p => (
                      <option key={p.person_id} value={p.person_id} className="bg-slate-900">
                        {p.name} ({p.person_id})
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>

            <form onSubmit={handleStep1Submit} className="space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    First Name <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                    placeholder="John"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                  {formErrors.firstName && <p className="text-xs text-rose-400 mt-1">{formErrors.firstName}</p>}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Last Name <span className="text-rose-400">*</span>
                  </label>
                  <input
                    type="text"
                    required
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                    placeholder="Doe"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                  {formErrors.lastName && <p className="text-xs text-rose-400 mt-1">{formErrors.lastName}</p>}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Employee / Person ID
                  </label>
                  <input
                    type="text"
                    value={employeeId}
                    onChange={(e) => setEmployeeId(e.target.value)}
                    placeholder={personId}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    System Role
                  </label>
                  <select
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 focus:outline-none focus:border-blue-500 transition-colors"
                  >
                    {ROLE_OPTIONS.map(r => <option key={r} value={r}>{r}</option>)}
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Department
                  </label>
                  <input
                    type="text"
                    value={department}
                    onChange={(e) => setDepartment(e.target.value)}
                    placeholder="Engineering / Security"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Designation
                  </label>
                  <input
                    type="text"
                    value={designation}
                    onChange={(e) => setDesignation(e.target.value)}
                    placeholder="Senior Specialist"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Email Address
                  </label>
                  <input
                    type="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="john.doe@company.com"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>

                <div>
                  <label className="block text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">
                    Phone Number
                  </label>
                  <input
                    type="text"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    placeholder="+1 (555) 000-0000"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-sm text-slate-100 placeholder-slate-600 focus:outline-none focus:border-blue-500 transition-colors"
                  />
                </div>
              </div>

              {formErrors.submit && (
                <div className="p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-300">
                  {formErrors.submit}
                </div>
              )}

              <div className="flex justify-end pt-4">
                <button
                  type="submit"
                  className="px-6 py-3 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-sm flex items-center gap-2 shadow-lg shadow-blue-600/20 transition-all hover:scale-[1.02]"
                >
                  Proceed to Capture Method <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </form>
          </div>
        )}

        {/* STEP 2: CAPTURE METHOD SELECTION */}
        {currentStep === 2 && (
          <div className="max-w-5xl mx-auto w-full space-y-6">
            <div className="text-center space-y-2 mb-8">
              <h2 className="text-2xl font-extrabold text-white tracking-tight">Select Face Acquisition Source</h2>
              <p className="text-sm text-slate-400">Choose between USB webcam, live CCTV camera stream, or photo file upload.</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Card 1: WEBCAM */}
              <div
                onClick={() => {
                  setCaptureMethod('WEBCAM')
                  setCurrentStep(3)
                }}
                className={clsx(
                  'group cursor-pointer bg-slate-900/80 border border-slate-800 rounded-3xl p-6 transition-all duration-300 hover:border-blue-500/60 hover:bg-slate-900 hover:shadow-2xl hover:shadow-blue-500/10 flex flex-col justify-between space-y-6 relative overflow-hidden',
                  captureMethod === 'WEBCAM' && 'ring-2 ring-blue-500 bg-slate-900'
                )}
              >
                <div className="w-14 h-14 rounded-2xl bg-blue-600/10 border border-blue-500/20 flex items-center justify-center text-blue-400 group-hover:scale-110 transition-transform">
                  <Camera className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white mb-2 flex items-center justify-between">
                    📷 USB Webcam
                    <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-blue-400 group-hover:translate-x-1 transition-all" />
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Live multi-angle capture using laptop camera or USB webcam with auto-pose guidance.
                  </p>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-blue-400 font-semibold uppercase tracking-wider">
                  <Sparkles className="w-3.5 h-3.5" /> Automated Quality Engine
                </div>
              </div>

              {/* Card 2: CCTV */}
              <div
                onClick={() => {
                  setCaptureMethod('CCTV')
                  setCurrentStep(3)
                }}
                className={clsx(
                  'group cursor-pointer bg-slate-900/80 border border-slate-800 rounded-3xl p-6 transition-all duration-300 hover:border-emerald-500/60 hover:bg-slate-900 hover:shadow-2xl hover:shadow-emerald-500/10 flex flex-col justify-between space-y-6 relative overflow-hidden',
                  captureMethod === 'CCTV' && 'ring-2 ring-emerald-500 bg-slate-900'
                )}
              >
                <div className="w-14 h-14 rounded-2xl bg-emerald-600/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 group-hover:scale-110 transition-transform">
                  <Video className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white mb-2 flex items-center justify-between">
                    🎥 CCTV Stream
                    <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-emerald-400 group-hover:translate-x-1 transition-all" />
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Acquire face samples directly from a live surveillance IP camera stream.
                  </p>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-emerald-400 font-semibold uppercase tracking-wider">
                  <Sparkles className="w-3.5 h-3.5" /> Track Locking
                </div>
              </div>

              {/* Card 3: PHOTO UPLOAD */}
              <div
                onClick={() => {
                  setCaptureMethod('UPLOAD')
                  setCurrentStep(3)
                }}
                className={clsx(
                  'group cursor-pointer bg-slate-900/80 border border-slate-800 rounded-3xl p-6 transition-all duration-300 hover:border-purple-500/60 hover:bg-slate-900 hover:shadow-2xl hover:shadow-purple-500/10 flex flex-col justify-between space-y-6 relative overflow-hidden',
                  captureMethod === 'UPLOAD' && 'ring-2 ring-purple-500 bg-slate-900'
                )}
              >
                <div className="w-14 h-14 rounded-2xl bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-400 group-hover:scale-110 transition-transform">
                  <Upload className="w-7 h-7" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-white mb-2 flex items-center justify-between">
                    📁 Photo File Upload
                    <ArrowRight className="w-4 h-4 text-slate-500 group-hover:text-purple-400 group-hover:translate-x-1 transition-all" />
                  </h3>
                  <p className="text-xs text-slate-400 leading-relaxed">
                    Upload 1 or more face photo files directly from your disk or phone.
                  </p>
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-purple-400 font-semibold uppercase tracking-wider">
                  <Sparkles className="w-3.5 h-3.5" /> Works Without Hardware Webcam
                </div>
              </div>
            </div>

            <div className="flex justify-start pt-4">
              <button
                onClick={() => setCurrentStep(1)}
                className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" /> Back to Person Info
              </button>
            </div>
          </div>
        )}

        {/* STEP 3: FACE CAPTURE WITH AI ASSISTANT */}
        {currentStep === 3 && (
          <div className="w-full space-y-4">
            {/* Sticky capture toolbar — always reachable without shrinking the window */}
            <div className="sticky top-0 z-30 bg-slate-950/90 backdrop-blur-md border border-slate-800 rounded-2xl px-4 py-3 flex flex-wrap items-center justify-between gap-3 shadow-lg">
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse flex-shrink-0" />
                <div className="min-w-0">
                  <h3 className="text-sm font-bold text-white uppercase tracking-wider truncate">
                    Face Capture · {captureMethod}
                  </h3>
                  <p className="text-[11px] text-slate-400">
                    {gallery.length} / {targetSamples} quality samples
                    {captureMethod === 'CCTV' && !targetLocked ? ' · Click a face to begin' : ''}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-2 flex-shrink-0">
                <button
                  onClick={() => setCurrentStep(2)}
                  className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 flex items-center gap-1.5"
                >
                  <ArrowLeft className="w-3.5 h-3.5" /> Method
                </button>
                <button
                  onClick={() => setCurrentStep(4)}
                  disabled={gallery.length === 0}
                  className={clsx(
                    'px-4 py-2 rounded-xl font-bold text-xs flex items-center gap-2 transition-all',
                    gallery.length > 0
                      ? 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-lg shadow-emerald-600/20'
                      : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  )}
                >
                  Review Capture ({gallery.length}) <ArrowRight className="w-3.5 h-3.5" />
                </button>
              </div>
            </div>

            {/* Collected samples strip — visible near top for quick review */}
            {gallery.length > 0 && (
              <div className="bg-slate-900/80 border border-slate-800 rounded-2xl px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-bold text-slate-300">Captured Samples</span>
                  <button
                    onClick={() => setCurrentStep(4)}
                    className="text-[11px] font-semibold text-emerald-400 hover:text-emerald-300"
                  >
                    Open full review →
                  </button>
                </div>
                <div className="flex gap-2 overflow-x-auto pb-1">
                  {gallery.map((sample) => (
                    <div key={sample.id} className="relative w-14 h-14 flex-shrink-0 rounded-xl overflow-hidden border border-slate-700 bg-slate-950 group">
                      <img src={sample.preview_url} alt="sample" className="w-full h-full object-cover" />
                      <div className="absolute bottom-0 inset-x-0 bg-slate-950/85 px-0.5 py-0.5 text-[7px] font-bold text-slate-200 uppercase truncate text-center">
                        {sample.pose_bin.replace(/_/g, ' ')}
                      </div>
                      <button
                        onClick={() => handleRemoveSample(sample.id)}
                        className="absolute inset-0 bg-rose-600/80 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity"
                        title="Remove sample"
                      >
                        <Trash2 className="w-3.5 h-3.5 text-white" />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 w-full">
            {/* Stream Preview Column */}
            <div className="xl:col-span-2 bg-slate-900/80 border border-slate-800 rounded-3xl p-4 shadow-2xl backdrop-blur-xl flex flex-col relative">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-bold text-slate-300 uppercase tracking-wider">
                    Live Preview
                  </h3>
                </div>

                {/* Webcam Device Selector */}
                {captureMethod === 'WEBCAM' && videoDevices.length > 1 && (
                  <select
                    value={selectedDeviceId}
                    onChange={(e) => {
                      setSelectedDeviceId(e.target.value)
                      startWebcam(e.target.value)
                    }}
                    className="bg-slate-950 border border-slate-800 text-xs text-slate-200 rounded-xl px-3 py-1.5 focus:outline-none"
                  >
                    {videoDevices.map((dev, idx) => (
                      <option key={dev.deviceId} value={dev.deviceId}>
                        {dev.label || `Camera ${idx + 1}`}
                      </option>
                    ))}
                  </select>
                )}

                {/* CCTV Camera Selector */}
                {captureMethod === 'CCTV' && cameraList.length > 0 && (
                  <select
                    value={selectedCameraId}
                    onChange={(e) => {
                      setSelectedCameraId(e.target.value)
                      setCctvError(false)
                      setCctvStreamKey(Date.now())
                    }}
                    className="bg-slate-950 border border-slate-800 text-xs text-slate-200 rounded-xl px-3 py-1.5 focus:outline-none"
                  >
                    {cameraList.map(c => {
                      const cid = c.id || c.camera_id
                      const isOnline = c.enabled && c.status !== 'OFFLINE'
                      return (
                        <option key={cid} value={cid}>
                          {c.name} ({cid}) {isOnline ? '🟢 Online' : '🔴 Offline'}
                        </option>
                      )
                    })}
                  </select>
                )}
              </div>

              {/* Stream Video Container — keep the CCTV frame visually clean and dominant */}
              <div
                className={clsx(
                  'relative w-full min-h-[320px] md:min-h-[420px] xl:min-h-[560px] bg-black rounded-2xl overflow-hidden border transition-all duration-300',
                  aiAssistant.face_detected && aiAssistant.centered
                    ? 'border-emerald-500/80 ring-2 ring-emerald-500/60 shadow-[0_0_30px_rgba(16,185,129,0.2)]'
                    : aiAssistant.face_detected
                    ? 'border-amber-500/80 ring-2 ring-amber-500/50 shadow-[0_0_25px_rgba(245,158,11,0.15)]'
                    : 'border-slate-800 shadow-xl'
                )}
              >
                {captureMethod === 'WEBCAM' && (
                  <>
                    <video
                      ref={videoRef}
                      autoPlay
                      playsInline
                      muted
                      className="w-full h-full object-cover transform -scale-x-100"
                    />
                    {webcamError && (
                      <div className="absolute inset-0 bg-slate-950/95 flex flex-col items-center justify-center p-6 text-center space-y-4">
                        <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-500">
                          <AlertCircle className="w-8 h-8" />
                        </div>
                        <div>
                          <h4 className="text-base font-bold text-white mb-1">Webcam Access Blocked</h4>
                          <p className="text-xs text-slate-300 max-w-md mx-auto leading-relaxed">{webcamError}</p>
                        </div>

                        <div className="flex items-center gap-3 pt-2">
                          <button
                            onClick={() => startWebcam()}
                            className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs flex items-center gap-1.5 shadow-lg shadow-blue-600/20"
                          >
                            <RefreshCw className="w-3.5 h-3.5" /> Retry Access
                          </button>

                          <button
                            onClick={() => {
                              setCaptureMethod('UPLOAD')
                              setWebcamError(null)
                            }}
                            className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-semibold text-xs flex items-center gap-1.5"
                          >
                            <Upload className="w-3.5 h-3.5" /> Switch to Photo Upload
                          </button>
                        </div>
                      </div>
                    )}
                  </>
                )}

                {captureMethod === 'CCTV' && (
                  isSelectedCamOnline && !cctvError ? (
                    <div className="relative w-full h-full flex items-center justify-center">
                      <img
                        ref={cctvImgRef}
                        key={`${selectedCameraId}_${cctvStreamKey}`}
                        src={`/video_feed/${selectedCameraId}`}
                        alt="CCTV Stream"
                        onLoad={() => setImgLoaded(prev => !prev)}
                        onError={() => {
                          setCctvError(true)
                        }}
                        className="w-full h-full object-contain bg-black"
                      />
                      {/* Single face-box layer (deduped) — keep detected faces visible without obscuring the feed */}
                      {!targetLocked && cctvFaces.map((f: any, idx: number) => {
                        const style = getOverlayBboxStyle(f.bbox)
                        if (!style.left) return null
                        const faceId = f.detection_id || `face_${idx}`
                        const isHovered = hoveredFaceId === faceId
                        return (
                          <div
                            key={faceId}
                            style={style}
                            onClick={() => handleSelectFace(f)}
                            onMouseEnter={() => setHoveredFaceId(faceId)}
                            onMouseLeave={() => setHoveredFaceId(null)}
                            title="Click to register this face"
                            className={clsx(
                              'absolute cursor-pointer rounded-[4px] z-10 box-border transition-all duration-150',
                              isHovered
                                ? 'border-[2px] border-sky-300/90 bg-sky-400/10 shadow-[0_0_10px_rgba(125,211,252,0.25)]'
                                : 'border-[1.5px] border-slate-200/80 bg-slate-950/10 hover:border-sky-300/80'
                            )}
                          />
                        )
                      })}

                      {/* After lock: highlight ONLY the target face with a compact, non-obtrusive marker */}
                      {targetLocked && targetDetails?.bbox && (
                        <div
                          style={getOverlayBboxStyle(targetDetails.bbox)}
                          className={clsx(
                            'absolute border-[2px] rounded-[4px] z-20 pointer-events-none',
                            targetState === 'TARGET_LOST' || targetState === 'TARGET_TEMPORARILY_LOST'
                              ? 'border-rose-500 bg-rose-500/10'
                              : 'border-emerald-400 bg-emerald-400/10 shadow-[0_0_12px_rgba(52,211,153,0.3)]'
                          )}
                        >
                          <div className={clsx(
                            'absolute -top-5 left-0 px-1.5 py-0.5 text-[9px] font-bold text-white rounded-sm',
                            targetState === 'TARGET_LOST' || targetState === 'TARGET_TEMPORARILY_LOST'
                              ? 'bg-rose-500'
                              : 'bg-emerald-500'
                          )}>
                            {targetState === 'TARGET_LOST' || targetState === 'TARGET_TEMPORARILY_LOST'
                              ? 'LOST'
                              : 'TARGET'}
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex flex-col items-center justify-center p-8 text-center space-y-4 bg-slate-950/90 w-full h-full">
                      <div className="w-14 h-14 rounded-2xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                        <Video className="w-8 h-8" />
                      </div>
                      <div>
                        <h4 className="text-base font-bold text-white mb-1">
                          {selectedCam ? selectedCam.name : 'Camera'} Stream Offline
                        </h4>
                        <p className="text-xs text-slate-400 max-w-md mx-auto">
                          {selectedCam ? `Camera ID: ${selectedCam.id || selectedCam.camera_id} (${selectedCam.location || 'Default Location'})` : 'No active camera selected'}
                        </p>
                        <p className="text-[11px] text-slate-500 mt-1">
                          Check camera power & RTSP configuration in Cameras tab or select another active camera.
                        </p>
                      </div>
                      <button
                        onClick={() => {
                          setCctvError(false)
                          setCctvStreamKey(Date.now())
                        }}
                        className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center gap-1.5 border border-slate-700"
                      >
                        <RefreshCw className="w-3.5 h-3.5" /> Retry Stream Connection
                      </button>
                    </div>
                  )
                )}

                {/* Track selector removed — face-first click-to-select only */}

                {captureMethod === 'UPLOAD' && (
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    className="w-full h-full flex flex-col items-center justify-center p-8 border-2 border-dashed border-purple-500/40 rounded-2xl bg-slate-950/80 hover:bg-slate-900/90 transition-all cursor-pointer space-y-4"
                  >
                    <div className="w-16 h-16 rounded-2xl bg-purple-600/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                      <Upload className="w-8 h-8" />
                    </div>
                    <div className="text-center">
                      <h4 className="text-sm font-bold text-white">Click to Select or Drop Face Photos</h4>
                      <p className="text-xs text-slate-400 mt-1">Supports JPG, PNG, WEBP (Multiple files allowed)</p>
                    </div>
                    {uploadingFiles && (
                      <div className="flex items-center gap-2 text-xs text-purple-400 font-semibold">
                        <RefreshCw className="w-4 h-4 animate-spin" /> Evaluating photos...
                      </div>
                    )}
                  </div>
                )}

              </div>

              {/* Bottom actions (secondary — primary Review is in sticky top bar) */}
              <div className="flex items-center justify-between pt-3 mt-1">
                <p className="text-[11px] text-slate-500">
                  Scroll if needed · Review Capture stays pinned at the top
                </p>
                <button
                  onClick={() => setCurrentStep(4)}
                  disabled={gallery.length === 0}
                  className={clsx(
                    'px-5 py-2 rounded-xl font-bold text-xs flex items-center gap-2 transition-all',
                    gallery.length > 0
                      ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                      : 'bg-slate-800 text-slate-500 cursor-not-allowed'
                  )}
                >
                  Review Gallery ({gallery.length}) <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* AI Assistant Column */}
            <div className="flex flex-col space-y-4 xl:sticky xl:top-20 xl:self-start">
              <AiAssistantPanel
                faceDetected={aiAssistant.face_detected}
                centered={aiAssistant.centered}
                sharp={aiAssistant.sharp}
                lighting={aiAssistant.lighting}
                eyesVisible={aiAssistant.eyes_visible}
                faceSizeOk={(aiAssistant as any).face_size_ok}
                identityVerified={(aiAssistant as any).identity_verified}
                currentPose={aiAssistant.current_pose}
                nextNeededPose={(aiAssistant as any).next_needed_pose}
                guidanceText={aiAssistant.guidance}
                statusMessage={aiAssistant.status}
                samplesCollected={gallery.length}
                targetSamples={targetSamples}
                progressPercent={Math.min(100, Math.round((gallery.length / Math.max(1, targetSamples)) * 100))}
                qualityScore={aiAssistant.quality_score}
                state={captureMethod === 'CCTV' ? targetState : undefined}
                poseCoverage={poseCoverage}
                target={captureMethod === 'CCTV' ? targetDetails : undefined}
                onChangeTarget={captureMethod === 'CCTV' ? handleChangeTarget : undefined}
              />
            </div>
            </div>
          </div>
        )}

        {/* STEP 4: GALLERY REVIEW */}
        {currentStep === 4 && (
          <div className="bg-slate-900/80 border border-slate-800 rounded-3xl p-6 md:p-8 shadow-2xl backdrop-blur-xl max-w-5xl mx-auto w-full space-y-6">
            <div className="flex items-center justify-between border-b border-slate-800 pb-5">
              <div>
                <h2 className="text-xl font-bold text-white flex items-center gap-2">
                  <ImageIcon className="w-5 h-5 text-indigo-400" /> Step 4: Review Face Gallery ({gallery.length} Samples)
                </h2>
                <p className="text-xs text-slate-400 mt-1">
                  Inspect captured pose diversity and quality scores before final FAISS embedding commit.
                </p>
              </div>

              <button
                onClick={() => setCurrentStep(3)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-200 flex items-center gap-1.5"
              >
                <RefreshCw className="w-4 h-4 text-blue-400" /> Capture More Poses
              </button>
            </div>

            {/* Gallery Grid */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-4">
              {gallery.map((sample, idx) => (
                <div
                  key={sample.id}
                  className="bg-slate-950 border border-slate-800 rounded-2xl p-2.5 flex flex-col justify-between space-y-2 group hover:border-blue-500/50 transition-all"
                >
                  <div className="relative aspect-square rounded-xl overflow-hidden bg-slate-900 border border-slate-800">
                    <img src={sample.preview_url} alt={sample.pose_bin} className="w-full h-full object-cover" />
                    <button
                      onClick={() => handleRemoveSample(sample.id)}
                      className="absolute top-1.5 right-1.5 p-1.5 rounded-lg bg-rose-600/90 text-white opacity-0 group-hover:opacity-100 transition-opacity"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </div>

                  <div>
                    <div className="text-[11px] font-bold text-slate-200 tracking-wide uppercase truncate">
                      {sample.pose_bin.replace('_', ' ')}
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-slate-400 mt-1">
                      <span>Score: {(sample.quality_score * 100).toFixed(0)}%</span>
                      <span>{sample.timestamp.includes(' ') || sample.timestamp.includes('T')
                        ? formatLocalTime(sample.timestamp)
                        : formatLocalTime(`1970-01-01 ${sample.timestamp}`)}</span>
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Duplicate identity warning (soft / hard) */}
            {duplicateChecking && (
              <div className="rounded-2xl border border-slate-700 bg-slate-950/60 px-4 py-3 text-xs text-slate-400 flex items-center gap-2">
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Checking gallery against existing identities...
              </div>
            )}

            {!duplicateChecking && duplicateCheck?.level === 'soft' && (
              <div className="rounded-2xl border border-amber-500/40 bg-amber-500/10 p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 flex-shrink-0">
                    <AlertTriangle className="w-5 h-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-bold text-amber-300">Possible duplicate person</h4>
                    <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                      This face looks similar to an existing person (e.g. glasses or lighting differences).
                      Prefer updating that profile instead of creating a new one.
                    </p>
                    <p className="text-xs text-amber-200/90 mt-2 font-mono">
                      Match: {duplicateCheck.matched_name || 'Unknown'} ({duplicateCheck.matched_person_id})
                      {' · '}
                      {Math.round((duplicateCheck.similarity || 0) * 100)}% similarity
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <button
                    type="button"
                    onClick={handleUpdateExistingFromWarning}
                    className="px-4 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-slate-950 text-xs font-bold"
                  >
                    Update existing
                  </button>
                  <button
                    type="button"
                    onClick={() => setSoftContinueAck(true)}
                    className={clsx(
                      'px-4 py-2 rounded-xl text-xs font-semibold border transition-colors',
                      softContinueAck
                        ? 'bg-slate-700 border-slate-600 text-slate-200'
                        : 'bg-slate-900 border-amber-500/40 text-amber-200 hover:bg-slate-800'
                    )}
                  >
                    {softContinueAck ? 'Continue acknowledged' : 'Continue anyway'}
                  </button>
                </div>
              </div>
            )}

            {!duplicateChecking && duplicateCheck?.level === 'hard' && (
              <div className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-4 space-y-3">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-xl bg-rose-500/20 border border-rose-500/30 flex items-center justify-center text-rose-400 flex-shrink-0">
                    <AlertCircle className="w-5 h-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <h4 className="text-sm font-bold text-rose-300">Duplicate face blocked</h4>
                    <p className="text-xs text-slate-300 mt-1 leading-relaxed">
                      A matching face is already registered. Commit is disabled — update the existing
                      profile or capture a different person.
                    </p>
                    <p className="text-xs text-rose-200/90 mt-2 font-mono">
                      Match: {duplicateCheck.matched_name || 'Unknown'} ({duplicateCheck.matched_person_id})
                      {' · '}
                      {Math.round((duplicateCheck.similarity || 0) * 100)}% similarity
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={handleUpdateExistingFromWarning}
                  className="px-4 py-2 rounded-xl bg-rose-500 hover:bg-rose-400 text-white text-xs font-bold"
                >
                  Update existing
                </button>
              </div>
            )}

            {/* Navigation Footer */}
            <div className="flex items-center justify-between pt-6 border-t border-slate-800">
              <button
                onClick={() => setCurrentStep(3)}
                className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-slate-300 flex items-center gap-2"
              >
                <ArrowLeft className="w-4 h-4" /> Back to Capture
              </button>

              <button
                onClick={handleCommitRegistration}
                disabled={!canCommit}
                className={clsx(
                  'px-8 py-3 rounded-xl text-white font-bold text-sm flex items-center gap-2 shadow-xl transition-all',
                  canCommit
                    ? 'bg-emerald-600 hover:bg-emerald-500 shadow-emerald-600/20 hover:scale-105'
                    : 'bg-slate-700 cursor-not-allowed opacity-60 shadow-none'
                )}
              >
                Save & Commit Registration <CheckCircle2 className="w-5 h-5" />
              </button>
            </div>
          </div>
        )}

        {/* STEP 5: PROCESSING & COMMIT */}
        {currentStep === 5 && (
          <div className="max-w-xl mx-auto w-full bg-slate-900/90 border border-slate-800 rounded-3xl p-8 shadow-2xl backdrop-blur-xl text-center space-y-6">
            {!registrationCompleted && !commitError && (
              <>
                <div className="w-20 h-20 rounded-3xl bg-blue-600/10 border border-blue-500/30 flex items-center justify-center text-blue-400 mx-auto animate-bounce">
                  <Cpu className="w-10 h-10 animate-spin" />
                </div>

                <div>
                  <h3 className="text-xl font-bold text-white mb-2">Finalizing Registration...</h3>
                  <p className="text-xs text-slate-400 font-mono">{processingStage}</p>
                </div>

                <div className="w-full bg-slate-800 h-2 rounded-full overflow-hidden p-0.5 border border-slate-700">
                  <div className="h-full bg-blue-500 rounded-full animate-pulse w-full" />
                </div>
              </>
            )}

            {commitError && (
              <div className="space-y-4">
                <div className="w-16 h-16 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-500 mx-auto">
                  <AlertCircle className="w-8 h-8" />
                </div>
                <h3 className="text-lg font-bold text-rose-400">Registration Failed</h3>
                <p className="text-xs text-slate-300 bg-rose-500/10 border border-rose-500/20 p-3 rounded-xl">{commitError}</p>
                <button
                  onClick={() => setCurrentStep(4)}
                  className="px-6 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-xs font-semibold text-white"
                >
                  Return to Review
                </button>
              </div>
            )}

            {registrationCompleted && (
              <div className="space-y-6">
                <div className="w-20 h-20 rounded-3xl bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 mx-auto">
                  <CheckCircle2 className="w-10 h-10" />
                </div>

                <div>
                  <h3 className="text-2xl font-extrabold text-white mb-1">Registration Complete!</h3>
                  <p className="text-xs text-slate-400">
                    Profile and multi-angle face embeddings successfully added to database & FAISS index.
                  </p>
                </div>

                <div className="flex items-center justify-center gap-4 pt-2">
                  <button
                    onClick={() => {
                      setCurrentStep(1)
                      setFirstName('')
                      setLastName('')
                      setEmployeeId('')
                      setGallery([])
                      setRegistrationCompleted(false)
                    }}
                    className="px-5 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold"
                  >
                    Register Another Person
                  </button>

                  <button
                    onClick={() => navigate('/persons')}
                    className="px-6 py-2.5 rounded-xl bg-blue-600 hover:bg-blue-500 text-white text-xs font-bold shadow-lg shadow-blue-600/20"
                  >
                    View Persons Gallery
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
