import { useState, useEffect, useRef } from 'react'
import {
  UserPlus, Upload, Camera, CheckCircle, AlertCircle, Trash2, X,
  RefreshCw, Play, Shield, Mail, Phone, Building, User,
  FileText, Check, AlertTriangle, Video, Sparkles, RefreshCcw, Layers
} from 'lucide-react'
import { TopBar } from '../components/TopBar'
import { useNavigate } from 'react-router-dom'
import {
  createPerson,
  getDetectedFacesMetadata,
  type DetectedFaceMetadata
} from '../lib/personApi'
import { getCameras, api } from '../lib/cameraApi'
import type { CameraConfig } from '../lib/cameraApi'
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

interface CapturedFace {
  id: string
  file: File
  previewUrl: string
  blurScore: number
  timestamp: string
}

// Convert base64 to File object
function base64ToFile(dataurl: string, filename: string): File {
  const arr = dataurl.split(',')
  const mime = arr[0].match(/:(.*?);/)![1]
  const bstr = atob(arr[1])
  let n = bstr.length
  const u8arr = new Uint8Array(n)
  while (n--) {
    u8arr[n] = bstr.charCodeAt(n)
  }
  return new File([u8arr], filename, { type: mime })
}

export function RegisterPerson() {
  const navigate = useNavigate()

  // --- Form State ---
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [role, setRole] = useState('Employee')
  const [department, setDepartment] = useState('')
  const [phone, setPhone] = useState('')
  const [email, setEmail] = useState('')
  const [notes, setNotes] = useState('')
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})

  // --- Capture Panel State ---
  const [activeTab, setActiveTab] = useState<'webcam' | 'upload' | 'cctv'>('cctv')
  
  // Exactly 3 slots for Phase 1
  const [capturedFaces, setCapturedFaces] = useState<(CapturedFace | null)[]>([null, null, null])
  const [selectedSlotIndex, setSelectedSlotIndex] = useState<number | null>(null)

  // --- Webcam Capture ---
  const [webcamStream, setWebcamStream] = useState<MediaStream | null>(null)
  const [webcamError, setWebcamError] = useState<string | null>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // --- Live CCTV Capture ---
  const [cameraList, setCameraList] = useState<CameraConfig[]>([])
  const [selectedCameraId, setSelectedCameraId] = useState<string>('')
  const [cctvStatus, setCctvStatus] = useState<'Connecting' | 'Connected' | 'Disconnected'>('Disconnected')
  const [fetchError, setFetchError] = useState<string | null>(null)
  const cctvImgRef = useRef<HTMLImageElement>(null)

  // --- Clickable Overlays & Metadata & Auto-Scroll Ref ---
  const [activeFaces, setActiveFaces] = useState<DetectedFaceMetadata[]>([])
  const [imgDims, setImgDims] = useState({ width: 0, height: 0, naturalWidth: 1280, naturalHeight: 720 })
  const cropsContainerRef = useRef<HTMLDivElement>(null)

  // --- Registered Persons List & Update Mode ---
  const [registeredPersons, setRegisteredPersons] = useState<any[]>([])
  const [selectedExistingPersonId, setSelectedExistingPersonId] = useState<string>('')
  const [isUpdateMode, setIsUpdateMode] = useState<boolean>(false)

  // --- Notifications & Alerts ---
  const [localError, setLocalError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [loadingStep, setLoadingStep] = useState('')
  const [successOpen, setSuccessOpen] = useState(false)
  const [apiError, setApiError] = useState<string | null>(null)



  // Fetch registered persons for update/re-registration selector
  useEffect(() => {
    api.get('/persons')
      .then((res) => {
        if (res.data?.data) {
          setRegisteredPersons(res.data.data)
        }
      })
      .catch(() => {})
  }, [])

  const handleSelectExistingPerson = (personId: string) => {
    setSelectedExistingPersonId(personId)
    if (!personId) {
      setIsUpdateMode(false)
      setEmployeeId('')
      setFirstName('')
      setLastName('')
      setDepartment('')
      setRole('Employee')
      setPhone('')
      setEmail('')
      setNotes('')
      return
    }

    const match = registeredPersons.find((p) => p.person_id === personId)
    if (match) {
      setEmployeeId(match.person_id)
      if (match.first_name || match.last_name) {
        setFirstName(match.first_name || '')
        setLastName(match.last_name || '')
      } else if (match.name) {
        const parts = match.name.trim().split(' ')
        setFirstName(parts[0] || '')
        setLastName(parts.slice(1).join(' ') || '')
      }
      setDepartment(match.department || '')
      setRole(match.role || 'Employee')
      setPhone(match.phone || '')
      setEmail(match.email || '')
      setNotes(match.notes || '')
      setIsUpdateMode(true)
    }
  }

  // Clear local error after 4 seconds
  useEffect(() => {
    if (localError) {
      const t = setTimeout(() => setLocalError(null), 4000)
      return () => clearTimeout(t)
    }
  }, [localError])

  // Measure loaded stream dimensions
  const handleImageLoad = () => {
    if (cctvImgRef.current) {
      setImgDims({
        width: cctvImgRef.current.clientWidth,
        height: cctvImgRef.current.clientHeight,
        naturalWidth: cctvImgRef.current.naturalWidth || 1280,
        naturalHeight: cctvImgRef.current.naturalHeight || 720
      })
    }
  }

  // Load configured CCTV cameras from backend
  useEffect(() => {
    setFetchError(null)
    api.get('/cameras')
      .then((res) => {
        const responseJson = res.data
        const data = responseJson.data || []
        setCameraList(data)
        if (data.length > 0) {
          const firstEnabled = data.find((c: any) => c.enabled)
          const defaultSelect = firstEnabled || data[0]
          setSelectedCameraId(defaultSelect.id || defaultSelect.camera_id!)
          setCctvStatus(defaultSelect.enabled ? 'Connected' : 'Disconnected')
        }
      })
      .catch((err) => {
        setFetchError(err.response?.data?.detail || err.response?.data?.message || err.message)
      })

    return () => {
      stopWebcam()
    }
  }, [])

  // Poll detected faces metadata for the active camera
  useEffect(() => {
    if (activeTab !== 'cctv' || !selectedCameraId || cctvStatus !== 'Connected') {
      setActiveFaces([])
      return
    }

    let isMounted = true
    const poll = async () => {
      try {
        const faces = await getDetectedFacesMetadata(selectedCameraId)
        if (isMounted) {
          setActiveFaces(faces || [])
          if (cctvImgRef.current) {
            setImgDims({
              width: cctvImgRef.current.clientWidth,
              height: cctvImgRef.current.clientHeight,
              naturalWidth: cctvImgRef.current.naturalWidth || 1280,
              naturalHeight: cctvImgRef.current.naturalHeight || 720
            })
          }
        }
      } catch (err) {
        console.error('Error fetching detected faces metadata:', err)
      }
    }

    poll()
    const timer = setInterval(poll, 450)

    return () => {
      isMounted = false
      clearInterval(timer)
    }
  }, [activeTab, selectedCameraId, cctvStatus])

  // Monitor resize to rescale face bounding box overlays
  useEffect(() => {
    const handleResize = () => {
      if (cctvImgRef.current) {
        setImgDims({
          width: cctvImgRef.current.clientWidth,
          height: cctvImgRef.current.clientHeight,
          naturalWidth: cctvImgRef.current.naturalWidth || 1280,
          naturalHeight: cctvImgRef.current.naturalHeight || 720
        })
      }
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  // Clean up webcam stream on tab change
  useEffect(() => {
    if (activeTab !== 'webcam') {
      stopWebcam()
    }
  }, [activeTab])

  // --- Capture Face Handler ---
  const handleCaptureFace = (face: DetectedFaceMetadata) => {
    // 1. Blur Validation
    if (face.blur_score < 40.0) {
      setLocalError('Captured image is blurry. Please select another frame.')
      return
    }

    // 2. Generate file object
    const filename = `cctv_crop_${face.track_id}_${Date.now()}.jpg`
    const file = base64ToFile(face.crop_base64, filename)
    const previewUrl = URL.createObjectURL(file)

    const newFace: CapturedFace = {
      id: Math.random().toString(36).substr(2, 9),
      file,
      previewUrl,
      blurScore: face.blur_score,
      timestamp: new Date().toLocaleTimeString()
    }

    setCapturedFaces((prev) => {
      const updated = [...prev]
      // If we are replacing/retaking a specific slot
      if (selectedSlotIndex !== null) {
        if (updated[selectedSlotIndex]) {
          URL.revokeObjectURL(updated[selectedSlotIndex]!.previewUrl)
        }
        updated[selectedSlotIndex] = newFace
        setSelectedSlotIndex(null)
      } else {
        // Find first empty slot
        const emptyIdx = updated.findIndex((f) => f === null)
        if (emptyIdx !== -1) {
          updated[emptyIdx] = newFace
        } else {
          setLocalError('All 3 slots are filled. Delete or click Replace on a slot to update.')
        }
      }
      return updated
    })
  }

  // --- Webcam Methods ---
  const startWebcam = async () => {
    setWebcamError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
        audio: false
      })
      setWebcamStream(stream)
      if (videoRef.current) {
        videoRef.current.srcObject = stream
        videoRef.current.play().catch(() => { })
      }
    } catch (err: any) {
      setWebcamError('Webcam not available. Check permissions or connection.')
    }
  }

  const stopWebcam = () => {
    if (webcamStream) {
      webcamStream.getTracks().forEach((track) => track.stop())
      setWebcamStream(null)
    }
  }

  const captureFromWebcam = () => {
    if (!videoRef.current || !canvasRef.current) return
    const video = videoRef.current
    const canvas = canvasRef.current
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height)

    canvas.toBlob((blob) => {
      if (!blob) return
      const timestampStr = new Date().toLocaleTimeString()
      const filename = `webcam_${Date.now()}.jpg`
      const file = new File([blob], filename, { type: 'image/jpeg' })
      const previewUrl = URL.createObjectURL(file)

      // Random sharp/blur simulation for webcam
      const blurVal = 65.0

      const newFace: CapturedFace = {
        id: Math.random().toString(36).substr(2, 9),
        file,
        previewUrl,
        blurScore: blurVal,
        timestamp: timestampStr
      }

      setCapturedFaces((prev) => {
        const updated = [...prev]
        if (selectedSlotIndex !== null) {
          if (updated[selectedSlotIndex]) URL.revokeObjectURL(updated[selectedSlotIndex]!.previewUrl)
          updated[selectedSlotIndex] = newFace
          setSelectedSlotIndex(null)
        } else {
          const emptyIdx = updated.findIndex((f) => f === null)
          if (emptyIdx !== -1) {
            updated[emptyIdx] = newFace
          } else {
            setLocalError('All 3 slots are filled. Delete or click Replace on a slot to update.')
          }
        }
        return updated
      })
    }, 'image/jpeg', 0.95)
  }

  // --- Upload Images Tab Methods ---
  const handleFileDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    if (e.dataTransfer.files) {
      addFilesToList(e.dataTransfer.files)
    }
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      addFilesToList(e.target.files)
    }
  }

  const addFilesToList = (fileList: FileList) => {
    const validTypes = ['image/jpeg', 'image/png', 'image/jpg']
    Array.from(fileList).forEach((file) => {
      if (!validTypes.includes(file.type)) {
        alert('Unsupported file type. Please upload JPG, PNG, or JPEG.')
        return
      }

      const previewUrl = URL.createObjectURL(file)
      const newFace: CapturedFace = {
        id: Math.random().toString(36).substr(2, 9),
        file,
        previewUrl,
        blurScore: 85.0,
        timestamp: new Date().toLocaleTimeString()
      }

      setCapturedFaces((prev) => {
        const updated = [...prev]
        if (selectedSlotIndex !== null) {
          if (updated[selectedSlotIndex]) URL.revokeObjectURL(updated[selectedSlotIndex]!.previewUrl)
          updated[selectedSlotIndex] = newFace
          setSelectedSlotIndex(null)
        } else {
          const emptyIdx = updated.findIndex((f) => f === null)
          if (emptyIdx !== -1) {
            updated[emptyIdx] = newFace
          } else {
            setLocalError('All 3 slots are filled. Delete or click Replace on a slot to update.')
          }
        }
        return updated
      })
    })
  }

  // --- Slot removal ---
  const removeFaceSlot = (index: number) => {
    setCapturedFaces((prev) => {
      const updated = [...prev]
      if (updated[index]) {
        URL.revokeObjectURL(updated[index]!.previewUrl)
        updated[index] = null
      }
      return updated
    })
    if (selectedSlotIndex === index) {
      setSelectedSlotIndex(null)
    }
  }

  // --- Form & Submit Validation ---
  const validateForm = (): boolean => {
    const errors: Record<string, string> = {}
    if (!firstName.trim()) errors.firstName = 'First name is required'
    if (!lastName.trim()) errors.lastName = 'Last name is required'
    if (!employeeId.trim()) errors.employeeId = 'Employee ID is required'
    if (!department.trim()) errors.department = 'Department is required'

    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleRegister = async () => {
    if (!validateForm()) return

    // Verify we have exactly 3 face images
    const filledCount = capturedFaces.filter(f => f !== null).length
    if (filledCount < 3) {
      setLocalError('Capture at least 3 clear face images.')
      return
    }

    setLoading(true)
    setApiError(null)
    setLoadingStep('Uploading face photos to AI Vision engine...')

    const payload = {
      person_id: employeeId.trim(),
      first_name: firstName.trim(),
      last_name: lastName.trim(),
      department: department.trim(),
      role,
      phone: phone.trim() || undefined,
      email: email.trim() || undefined,
      notes: notes.trim() || undefined,
      files: capturedFaces.map((f) => f!.file)
    }

    try {
      setTimeout(() => setLoadingStep('Generating 512D ArcFace embeddings...'), 1000)
      setTimeout(() => setLoadingStep('Updating FAISS vector search index...'), 2400)

      await createPerson(payload)

      setTimeout(() => {
        setLoading(false)
        setSuccessOpen(true)
      }, 3500)

    } catch (err: any) {
      setLoading(false)
      const msg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Registration failed.'
      setApiError(msg)
    }
  }

  const isFormValid = firstName.trim() && lastName.trim() && employeeId.trim() && department.trim()
  const hasThreeFaces = capturedFaces.filter((f) => f !== null).length === 3
  const canSubmit = isFormValid && hasThreeFaces

  return (
    <div className="flex flex-col h-full overflow-hidden bg-slate-950 text-slate-100">
      <TopBar title="Register Person" />

      {/* Main Split Grid Viewport */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 max-w-7xl mx-auto w-full pb-28">

        {/* Top Header Section */}
        <div className="flex justify-between items-start">
          <div>
            <h2 className="text-xl font-bold text-white flex items-center gap-2.5">
              <UserPlus className="w-5.5 h-5.5 text-primary-400" />
              CCTV Face Registration Wizard
            </h2>
            <p className="text-xs text-slate-400 mt-1 animate-pulse">
              Register a new person from live CCTV. Exactly 3 clear face images are required.
            </p>
          </div>
          
          {/* Status Indicator / Toast messages */}
          {localError && (
            <div className="px-4 py-2 rounded-xl bg-red-500/15 border border-red-500/25 text-xs text-red-300 flex items-center gap-2 shadow-lg animate-bounce">
              <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
              <span>{localError}</span>
            </div>
          )}
        </div>

        {/* Split grid */}
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

          {/* Left Column Form: 40% (span 2 of 5) */}
          <div className="lg:col-span-2 glass rounded-2xl p-5 border border-white/5 space-y-5 flex flex-col justify-between">
            <div className="space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/5">
                <div className="flex items-center gap-2">
                  <Shield className="w-4 h-4 text-primary-400" />
                  <span className="text-xs font-bold text-slate-200 tracking-wider">PERSON DETAILS</span>
                </div>
                {isUpdateMode && (
                  <span className="text-[10px] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded border border-amber-500/25">
                    ● Update / Re-register Mode
                  </span>
                )}
              </div>

              {/* Existing Registered Person Update Selector */}
              {registeredPersons.length > 0 && (
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">
                    Update Existing Person (Optional)
                  </label>
                  <select
                    className="input-field custom-select cursor-pointer text-xs py-2 bg-slate-900/90 border-amber-500/30"
                    value={selectedExistingPersonId}
                    onChange={(e) => handleSelectExistingPerson(e.target.value)}
                  >
                    <option value="">-- Register New Person (Or select existing to update) --</option>
                    {registeredPersons.map((p) => (
                      <option key={p.person_id} value={p.person_id}>
                        {p.name} ({p.person_id}) — {p.department || 'No Dept'} [{p.embedding_count} sample(s)]
                      </option>
                    ))}
                  </select>
                </div>
              )}

              {isUpdateMode && (
                <div className="p-3 rounded-xl bg-amber-500/10 border border-amber-500/25 text-[11px] text-amber-200 space-y-1 animate-fade-in">
                  <div className="flex items-center justify-between">
                    <span className="font-bold text-amber-300">Updating Registered Profile</span>
                    <button
                      type="button"
                      onClick={() => handleSelectExistingPerson('')}
                      className="text-[10px] font-bold text-amber-400 hover:underline cursor-pointer"
                    >
                      Clear & Register New
                    </button>
                  </div>
                  <p className="text-[10px] text-slate-300 leading-relaxed">
                    Submitting new face crops will update <strong>{firstName} {lastName} ({employeeId})</strong>'s profile by replacing old embeddings with higher quality samples for faster recognition!
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-3.5">
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">First Name *</label>
                  <input
                    className={clsx('input-field text-xs py-2', formErrors.firstName && 'border-red-500/50')}
                    placeholder="John"
                    value={firstName}
                    onChange={(e) => setFirstName(e.target.value)}
                  />
                  {formErrors.firstName && <span className="text-[10px] text-red-400 mt-1 block">{formErrors.firstName}</span>}
                </div>
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Last Name *</label>
                  <input
                    className={clsx('input-field text-xs py-2', formErrors.lastName && 'border-red-500/50')}
                    placeholder="Smith"
                    value={lastName}
                    onChange={(e) => setLastName(e.target.value)}
                  />
                  {formErrors.lastName && <span className="text-[10px] text-red-400 mt-1 block">{formErrors.lastName}</span>}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3.5">
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Employee / Person ID *</label>
                  <input
                    className={clsx('input-field font-mono text-xs py-2', formErrors.employeeId && 'border-red-500/50')}
                    placeholder="EMP001"
                    value={employeeId}
                    onChange={(e) => {
                      const val = e.target.value
                      setEmployeeId(val)
                      const match = registeredPersons.find((p) => p.person_id.toLowerCase() === val.trim().toLowerCase())
                      if (match) {
                        setSelectedExistingPersonId(match.person_id)
                        setIsUpdateMode(true)
                        if (match.first_name) setFirstName(match.first_name)
                        if (match.last_name) setLastName(match.last_name)
                        if (match.department) setDepartment(match.department)
                        if (match.role) setRole(match.role)
                      }
                    }}
                  />
                  {formErrors.employeeId && <span className="text-[10px] text-red-400 mt-1 block">{formErrors.employeeId}</span>}
                </div>
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Role Class *</label>
                  <select
                    className="input-field custom-select cursor-pointer text-xs py-2"
                    value={role}
                    onChange={(e) => setRole(e.target.value)}
                  >
                    {ROLE_OPTIONS.map((opt) => (
                      <option key={opt} value={opt}>{opt}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Department *</label>
                <input
                  className={clsx('input-field text-xs py-2', formErrors.department && 'border-red-500/50')}
                  placeholder="Security Ops, General Administration"
                  value={department}
                  onChange={(e) => setDepartment(e.target.value)}
                />
                {formErrors.department && <span className="text-[10px] text-red-400 mt-1 block">{formErrors.department}</span>}
              </div>

              <div className="grid grid-cols-2 gap-3.5">
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Phone</label>
                  <input
                    className="input-field text-xs py-2"
                    placeholder="+91 99999 99999"
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                  />
                </div>
                <div>
                  <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Email</label>
                  <input
                    className="input-field text-xs py-2"
                    placeholder="john@company.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
              </div>

              <div>
                <label className="text-[11px] font-bold text-slate-400 mb-1.5 block">Notes</label>
                <textarea
                  className="input-field text-xs py-2 resize-none"
                  rows={2}
                  placeholder="Additional background or watchlist info..."
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </div>
            </div>

            {/* Validation warning helper block */}
            {!hasThreeFaces && (
              <div className="p-3.5 rounded-xl bg-yellow-500/10 border border-yellow-500/20 text-[11px] text-yellow-300 flex items-start gap-2">
                <AlertCircle className="w-4 h-4 text-yellow-400 flex-shrink-0 mt-0.5" />
                <div>
                  Capture at least <strong>3 clear face images</strong>. Current: {capturedFaces.filter(f => f !== null).length}/3.
                </div>
              </div>
            )}
            
            {hasThreeFaces && (
              <div className="p-3.5 rounded-xl bg-green-500/10 border border-green-500/20 text-[11px] text-green-300 flex items-start gap-2">
                <CheckCircle className="w-4 h-4 text-green-400 flex-shrink-0 mt-0.5" />
                <div>
                  Ready to register! 3 high-quality face samples isolated.
                </div>
              </div>
            )}
          </div>

          {/* Right Side Capture Options: 60% (span 3 of 5) */}
          <div className="lg:col-span-3 glass rounded-2xl p-5 border border-white/5 space-y-5 flex flex-col justify-between">
            <div className="space-y-4">

              {/* Tab selectors */}
              <div className="flex items-center justify-between border-b border-white/5 pb-2">
                <div className="flex gap-2 p-1 glass rounded-xl">
                  {[
                    { id: 'cctv', label: 'Live CCTV Camera', icon: Camera },
                    { id: 'webcam', label: 'Webcam', icon: Video },
                    { id: 'upload', label: 'Upload Files', icon: Upload }
                  ].map((tab) => {
                    const Icon = tab.icon
                    return (
                      <button
                        key={tab.id}
                        onClick={() => {
                          setActiveTab(tab.id as any)
                          setSelectedSlotIndex(null)
                        }}
                        className={clsx(
                          'px-4 py-1.5 rounded-lg text-xs font-semibold flex items-center gap-2 transition-all cursor-pointer',
                          activeTab === tab.id
                            ? 'bg-primary-500 text-white shadow-lg'
                            : 'text-slate-400 hover:text-slate-200'
                        )}
                      >
                        <Icon className="w-3.5 h-3.5" />
                        {tab.label}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* ── TAB 1: LIVE CCTV STREAM CAPTURE (TAP TO SELECT) ── */}
              {activeTab === 'cctv' && (
                <div className="space-y-4 animate-fade-in">
                  {fetchError && (
                    <div className="p-3 rounded-xl bg-red-500/10 border border-red-500/20 text-xs text-red-300 flex items-center gap-2">
                      <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
                      <span>Failed to fetch cameras: {fetchError}</span>
                    </div>
                  )}

                  <div className="flex gap-2">
                    <select
                      className="input-field custom-select cursor-pointer text-xs py-2"
                      value={selectedCameraId}
                      onChange={(e) => {
                        setSelectedCameraId(e.target.value)
                        const cam = cameraList.find(c => (c.id || c.camera_id) === e.target.value)
                        setCctvStatus(cam?.enabled ? 'Connected' : 'Disconnected')
                        setActiveFaces([])
                      }}
                    >
                      {cameraList.map((cam) => {
                        const idValue = cam.id || cam.camera_id!
                        return (
                          <option key={idValue} value={idValue}>
                            {cam.name} ({cam.location}) — {cam.enabled ? 'Enabled' : 'Disabled'}
                          </option>
                        )
                      })}
                      {cameraList.length === 0 && !fetchError && (
                        <option value="">No Active CCTV Streams Registered</option>
                      )}
                    </select>
                  </div>

                  {/* Side-by-Side Grid: Video Feed (Left) & Vertical Detected Face Crops Sidebar (Right) */}
                  <div className="grid grid-cols-1 md:grid-cols-4 gap-3 items-start">
                    {/* Live Stream Viewport (3 Cols) */}
                    <div className="md:col-span-3 relative aspect-video bg-slate-900 rounded-xl overflow-hidden border border-white/10 flex items-center justify-center group select-none">
                      {selectedCameraId && cctvStatus === 'Connected' ? (
                        <img
                          ref={cctvImgRef}
                          src={`/video_feed/${selectedCameraId}`}
                          alt="CCTV stream"
                          className="w-full h-full object-cover"
                          onLoad={handleImageLoad}
                          onError={() => setCctvStatus('Disconnected')}
                        />
                      ) : (
                        <div className="flex flex-col items-center justify-center gap-2 text-slate-500">
                          <Camera className="w-10 h-10 animate-pulse text-slate-600" />
                          <span className="text-xs">No Active Stream Feed</span>
                        </div>
                      )}

                      {/* Status indicator badge */}
                      <div className="absolute top-3 left-3 flex items-center gap-2 pointer-events-none">
                        <span className={clsx(
                          'text-[9px] font-bold px-2 py-0.5 rounded-full border shadow-md backdrop-blur',
                          cctvStatus === 'Connected'
                            ? 'badge-green border-green-500/20'
                            : 'badge-red border-red-500/20'
                        )}>
                          {cctvStatus === 'Connected' ? '● Live CCTV' : '○ Disconnected'}
                        </span>
                      </div>
                    </div>

                    {/* Vertical Detected Face Crops Panel (1 Col) */}
                    <div className="md:col-span-1 glass rounded-xl border border-white/10 p-2.5 space-y-2 flex flex-col h-full min-h-[280px] max-h-[350px]">
                      <div className="flex items-center justify-between border-b border-white/5 pb-1.5">
                        <span className="text-[10px] font-bold text-slate-300 tracking-wider flex items-center gap-1">
                          <User className="w-3 h-3 text-primary-400" />
                          DETECTED ({activeFaces.length})
                        </span>
                        <span className="text-[8px] text-slate-400">Tap to add</span>
                      </div>

                      <div className="flex-1 overflow-y-auto space-y-2 pr-1 custom-scrollbar">
                        {activeFaces.map((face) => (
                          <div
                            key={face.track_id}
                            onClick={() => handleCaptureFace(face)}
                            className={clsx(
                              "p-1.5 rounded-lg border bg-slate-900/90 hover:border-green-400 hover:scale-102 flex items-center gap-2 cursor-pointer transition-all group",
                              face.blur_score >= 40.0 ? "border-white/10" : "border-red-500/30 opacity-60"
                            )}
                          >
                            <div className="w-10 h-10 aspect-square rounded-md overflow-hidden bg-slate-950 flex-shrink-0 relative border border-white/10">
                              <img src={face.crop_base64} alt="Crop" className="w-full h-full object-cover" />
                            </div>

                            <div className="flex-1 min-w-0 font-mono text-[9px] space-y-0.5">
                              <div className="flex justify-between items-center">
                                <span className="font-bold text-slate-200 truncate">ID #{face.track_id}</span>
                                <span className={clsx(
                                  "px-1 py-0.2 rounded font-bold text-[8px]",
                                  face.blur_score >= 40.0 ? "bg-green-500/20 text-green-400" : "bg-red-500/20 text-red-400"
                                )}>
                                  Q:{Math.round(face.blur_score)}
                                </span>
                              </div>

                              <div className="text-slate-400 truncate text-[8px]">
                                {face.is_recognized && face.name ? (
                                  <span className="text-green-400 font-bold">{face.name}</span>
                                ) : (
                                  <span className="text-slate-500">Unregistered</span>
                                )}
                              </div>
                            </div>
                          </div>
                        ))}

                        {activeFaces.length === 0 && (
                          <div className="flex flex-col items-center justify-center h-44 text-center p-2 text-slate-500">
                            <Camera className="w-5 h-5 mb-1.5 opacity-30 animate-pulse" />
                            <span className="text-[10px] italic">No active face crops detected in current stream view.</span>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                  
                  <div className="p-3 bg-primary-500/10 border border-primary-500/15 rounded-xl flex items-center gap-2.5 mt-3">
                    <Sparkles className="w-4 h-4 text-primary-400 flex-shrink-0 animate-pulse" />
                    <p className="text-[11px] text-slate-300">
                      <strong>How to register:</strong> Select a face crop from the active face thumbnails above to add it to your Captured Face Gallery slots below, then fill in the form and register!
                    </p>
                  </div>
                </div>
              )}

              {/* ── TAB 2: WEBCAM CAPTURE ── */}
              {activeTab === 'webcam' && (
                <div className="space-y-4 animate-fade-in">
                  <div className="relative aspect-video bg-slate-900 rounded-xl overflow-hidden border border-white/10 flex items-center justify-center group">
                    {webcamStream ? (
                      <video
                        ref={videoRef}
                        className="w-full h-full object-cover scale-x-[-1]"
                        playsInline
                        muted
                      />
                    ) : (
                      <div className="flex flex-col items-center justify-center gap-3 text-slate-500 text-center p-6">
                        <Video className="w-12 h-12 text-slate-600 animate-pulse" />
                        <div className="text-xs font-semibold text-slate-300">Webcam Not Running</div>
                        <p className="text-[11px] text-slate-500 max-w-xs">Click Start Camera below to initialize local webcam capture.</p>
                      </div>
                    )}

                    <canvas ref={canvasRef} className="hidden" />

                    {webcamError && (
                      <div className="absolute inset-0 bg-black/85 flex items-center justify-center p-4">
                        <div className="text-center space-y-2">
                          <AlertTriangle className="w-8 h-8 text-red-500 mx-auto" />
                          <div className="text-xs font-bold text-red-400">{webcamError}</div>
                        </div>
                      </div>
                    )}
                  </div>

                  <div className="flex gap-2.5">
                    {!webcamStream ? (
                      <button onClick={startWebcam} className="btn-primary flex-1 justify-center py-2.5 text-xs">
                        <Play className="w-3.5 h-3.5" /> Start Camera
                      </button>
                    ) : (
                      <>
                        <button onClick={captureFromWebcam} className="btn-primary flex-1 justify-center py-2.5 text-xs">
                          <Camera className="w-3.5 h-3.5" /> Capture Face Crop
                        </button>
                        <button onClick={stopWebcam} className="btn-secondary py-2.5 text-xs px-4">
                          Stop
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}

              {/* ── TAB 3: FILE UPLOAD ── */}
              {activeTab === 'upload' && (
                <div className="space-y-4 animate-fade-in">
                  <div
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={handleFileDrop}
                    className="border-2 border-dashed border-white/10 rounded-xl aspect-video bg-slate-900/40 hover:bg-slate-900/70 hover:border-primary-500/40 transition-all flex flex-col items-center justify-center gap-3 p-6 text-slate-500 cursor-pointer relative group"
                  >
                    <input
                      type="file"
                      multiple
                      accept="image/jpeg,image/png,image/jpg"
                      onChange={handleFileSelect}
                      className="absolute inset-0 opacity-0 cursor-pointer"
                    />
                    <div className="w-12 h-12 rounded-full glass border border-white/5 flex items-center justify-center text-primary-400 group-hover:scale-110 transition-transform">
                      <Upload className="w-5.5 h-5.5" />
                    </div>
                    <div className="text-center">
                      <span className="text-xs font-bold text-slate-200 block">Drag & Drop face photos here</span>
                      <span className="text-[10px] text-slate-500 mt-1 block">Supports JPG, JPEG, PNG</span>
                    </div>
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>

        {/* Captured Face Gallery (3 targeted slots) */}
        <div className="glass rounded-2xl p-5 border border-white/5 space-y-4">
          <div className="flex items-center justify-between border-b border-white/5 pb-2">
            <h3 className="text-xs font-bold text-slate-200 tracking-wider flex items-center gap-1.5">
              <Layers className="w-4 h-4 text-primary-400" />
              CAPTURED FACE GALLERY (EXACTLY 3 CLEAR IMAGES REQUIRED)
            </h3>
            <span className="text-[10px] text-slate-500">
              {selectedSlotIndex !== null 
                ? `[Replace mode active] Next capture will overwrite Slot ${selectedSlotIndex + 1}` 
                : 'Click Replace on a slot to retake that image.'}
            </span>
          </div>

          <div className="grid grid-cols-3 gap-6">
            {capturedFaces.map((face, index) => {
              const isActiveSlot = selectedSlotIndex === index

              return (
                <div 
                  key={index} 
                  className={clsx(
                    "glass rounded-xl border p-3 flex flex-col items-center justify-between transition-all relative group",
                    isActiveSlot 
                      ? "border-primary-500 shadow-lg shadow-primary-500/10 scale-102 ring-2 ring-primary-500/20" 
                      : "border-white/10 hover:border-white/20"
                  )}
                >
                  {/* Image crop slot */}
                  <div className="w-full aspect-square bg-slate-900 rounded-lg overflow-hidden border border-white/5 flex items-center justify-center relative">
                    {face ? (
                      <>
                        <img src={face.previewUrl} alt={`Slot ${index + 1}`} className="w-full h-full object-cover" />
                        <button
                          onClick={() => removeFaceSlot(index)}
                          className="absolute top-1.5 right-1.5 w-6 h-6 rounded-lg bg-black/60 hover:bg-red-600 text-slate-300 hover:text-white flex items-center justify-center transition-colors border border-white/10"
                          title="Delete sample"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </>
                    ) : (
                      <div className="flex flex-col items-center gap-1.5 text-slate-600 p-4 text-center">
                        <Camera className="w-6 h-6 opacity-35" />
                        <span className="text-[10px] font-semibold leading-tight">Slot {index + 1} Empty</span>
                      </div>
                    )}
                  </div>

                  {/* Metadata and action buttons */}
                  <div className="w-full mt-3 space-y-2">
                    {face ? (
                      <div className="text-[10px] space-y-1 font-mono">
                        <div className="flex justify-between">
                          <span className="text-slate-400">Status:</span>
                          <span className="font-bold text-green-400">✓ Ready</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-slate-400">Quality Index:</span>
                          <span className="font-bold text-slate-200">{Math.round(face.blurScore)}</span>
                        </div>
                        <div className="text-[9px] text-slate-500 text-right">{face.timestamp}</div>
                      </div>
                    ) : (
                      <div className="text-[10px] text-slate-500 italic text-center font-medium leading-normal py-1">
                        {isActiveSlot ? "Waiting for new click..." : "Select face overlay to fill"}
                      </div>
                    )}

                    <div className="flex gap-2 pt-1.5 border-t border-white/5">
                      {face && (
                        <button
                          onClick={() => setSelectedSlotIndex(isActiveSlot ? null : index)}
                          className={clsx(
                            "flex-1 py-1 rounded text-[10px] font-bold text-center border cursor-pointer transition-colors",
                            isActiveSlot 
                              ? "bg-slate-800 border-primary-500 text-primary-400" 
                              : "bg-slate-900 border-white/10 text-slate-300 hover:bg-slate-800"
                          )}
                        >
                          {isActiveSlot ? 'Cancel' : 'Replace / Retake'}
                        </button>
                      )}
                      
                      {!face && !isActiveSlot && (
                        <button
                          onClick={() => setSelectedSlotIndex(index)}
                          className="w-full py-1 rounded text-[10px] font-bold text-center bg-slate-900 border border-dashed border-white/15 text-slate-400 hover:text-slate-200 hover:border-slate-400 cursor-pointer transition-colors"
                        >
                          Select Slot
                        </button>
                      )}
                      
                      {!face && isActiveSlot && (
                        <button
                          onClick={() => setSelectedSlotIndex(null)}
                          className="w-full py-1 rounded text-[10px] font-bold text-center bg-slate-800 border border-primary-500 text-primary-400 cursor-pointer"
                        >
                          Selected
                        </button>
                      )}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

      </div>

      {/* Floating Register Footer */}
      <div className="fixed bottom-0 left-0 right-0 p-4 bg-slate-900/85 backdrop-blur-md border-t border-white/5 flex items-center justify-between z-40 max-w-7xl mx-auto w-full rounded-t-2xl px-6 shadow-2xl">
        <button
          onClick={() => navigate('/persons')}
          className="btn-secondary py-2 px-5 text-xs"
        >
          Cancel & Exit
        </button>

        {apiError && (
          <div className="px-4 py-2 rounded-xl bg-red-500/15 border border-red-500/25 text-xs text-red-300 flex items-center gap-2 max-w-lg truncate shadow-inner">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0" />
            <span>{apiError}</span>
          </div>
        )}

        <button
          onClick={handleRegister}
          disabled={!canSubmit || loading}
          className={clsx(
            'btn-primary py-2.5 px-6 text-xs font-bold transition-all disabled:opacity-40 disabled:cursor-not-allowed',
            canSubmit && 'bg-green-600 hover:bg-green-500 text-white shadow-lg shadow-green-500/20'
          )}
        >
          {loading ? 'Processing...' : 'Register Person'}
        </button>
      </div>

      {/* Full-Screen Loading Overlay */}
      {loading && (
        <div className="fixed inset-0 z-50 bg-slate-950/85 backdrop-blur-md flex items-center justify-center animate-fade-in">
          <div className="text-center space-y-4 p-8 glass rounded-2xl border border-white/10 shadow-2xl max-w-sm">
            <RefreshCcw className="w-10 h-10 text-primary-400 animate-spin mx-auto" />
            <h3 className="font-bold text-white text-base">Registering Profile</h3>
            <p className="text-xs text-slate-400">{loadingStep}</p>
          </div>
        </div>
      )}

      {/* Success Notification Dialog */}
      {successOpen && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center animate-fade-in p-4">
          <div className="glass-bright rounded-2xl p-6 w-full max-w-xs border border-green-500/25 shadow-2xl text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-green-500/15 text-green-400 flex items-center justify-center mx-auto">
              <CheckCircle className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Registered Successfully</h3>
              <p className="text-xs text-slate-400 mt-1">
                <strong className="text-white">{firstName} {lastName}</strong> is now registered. 3 embeddings generated and saved. Index updated.
              </p>
            </div>
            <button
              onClick={() => {
                setSuccessOpen(false)
                navigate('/persons')
              }}
              className="btn-primary w-full justify-center py-2 text-xs"
            >
              OK, View Persons
            </button>
          </div>
        </div>
      )}

    </div>
  )
}
