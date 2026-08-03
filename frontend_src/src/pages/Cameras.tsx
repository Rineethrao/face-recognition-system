import { useEffect, useState } from 'react'
import {
  Plus, Edit2, Trash2, Wifi, WifiOff, Camera as CameraIcon,
  CheckCircle, AlertCircle, X, Shield, RefreshCw, Eye,
  Maximize2, ArrowRight, ArrowLeft, Play, Cpu, HardDrive
} from 'lucide-react'
import { TopBar } from '../components/TopBar'
import { useStore } from '../store/useStore'
import {
  getCameras, getCamera, createCamera, updateCamera, deleteCamera,
  testCameraConnection, getStreamUrl
} from '../lib/cameraApi'
import type { CameraConfig, CameraCreatePayload, CameraTestResult } from '../lib/cameraApi'
import clsx from 'clsx'

const CAMERA_BRANDS = [
  { id: 'CP Plus', name: 'CP Plus' },
  { id: 'Hikvision', name: 'Hikvision' },
  { id: 'Securus', name: 'Securus' },
  { id: 'Dahua', name: 'Dahua' },
  { id: 'Axis', name: 'Axis' },
  { id: 'ONVIF', name: 'ONVIF Standard' },
  { id: 'Custom', name: 'Custom RTSP' },
]

const ROTATION_OPTIONS = [0, 90, 180, 270]

// ─────────────────────────────────────────────────────────────────────────────
// Multi-Step Add / Edit Camera Wizard Dialog
// ─────────────────────────────────────────────────────────────────────────────

interface WizardProps {
  initial?: CameraConfig | null
  onSuccess: () => void
  onClose: () => void
}

function AddEditCameraWizard({ initial, onSuccess, onClose }: WizardProps) {
  const [step, setStep] = useState<1 | 2 | 3>(1)
  const [form, setForm] = useState<CameraCreatePayload>({
    id: initial?.id || initial?.camera_id,
    camera_id: initial?.camera_id || initial?.id,
    name: initial?.name || '',
    location: initial?.location || 'DFT Office',
    description: initial?.description || '',
    brand: initial?.brand || 'CP Plus',
    ip_address: initial?.ip_address || '',
    port: initial?.port || 554,
    username: initial?.username || '',
    password: initial?.password || '',
    channel: initial?.channel || 1,
    stream_type: (initial?.stream_type as any) || 'sub',
    enabled: initial?.enabled ?? true,
    rotation: initial?.rotation || 0,
    source: initial?.source || '',
  })

  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<CameraTestResult | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleTestConnection = async () => {
    setTesting(true)
    setTestError(null)
    setTestResult(null)

    try {
      const res = await testCameraConnection({
        brand: form.brand,
        ip_address: form.ip_address,
        port: form.port,
        username: form.username,
        password: form.password,
        channel: form.channel,
        stream_type: form.stream_type,
        source: form.source,
      })
      setTestResult(res)
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Connection test failed.'
      setTestError(msg)
    } finally {
      setTesting(false)
    }
  }

  const handleSave = async () => {
    setSaving(true)
    setError(null)

    try {
      const camId = (initial?.id || initial?.camera_id)
      const payload: CameraCreatePayload = {
        ...form,
        source: undefined // Force backend to construct fresh RTSP URL matching ip_address & credentials
      }

      if (camId) {
        await updateCamera(camId, payload)
      } else {
        await createCamera(payload)
      }
      onSuccess()
      onClose()
    } catch (err: any) {
      const msg = err.response?.data?.detail || err.response?.data?.message || err.message || 'Failed to save camera.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in p-4 overflow-y-auto">
      <div className="glass-bright rounded-2xl p-6 w-full max-w-xl border border-white/10 shadow-2xl space-y-6 my-8">

        {/* Modal Header */}
        <div className="flex items-center justify-between border-b border-white/10 pb-4">
          <div>
            <h3 className="font-bold text-white text-lg flex items-center gap-2">
              <CameraIcon className="w-5 h-5 text-primary-400" />
              {initial ? 'Edit Camera' : 'Add New CCTV Camera'}
            </h3>
            <p className="text-xs text-slate-400 mt-0.5">
              Backend automatically generates RTSP URLs and manages worker threads.
            </p>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/5 transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Step Indicator */}
        <div className="flex items-center justify-between glass rounded-xl p-2 text-xs font-semibold">
          {[
            { num: 1, title: 'General Info' },
            { num: 2, title: 'Connection Setup' },
            { num: 3, title: 'Validation & Preview' },
          ].map(s => (
            <button
              key={s.num}
              onClick={() => setStep(s.num as any)}
              className={clsx(
                'flex-1 py-1.5 rounded-lg flex items-center justify-center gap-2 transition-all',
                step === s.num
                  ? 'bg-primary-500 text-white shadow-lg'
                  : step > s.num
                  ? 'text-green-400 bg-green-500/10'
                  : 'text-slate-500 hover:text-slate-300'
              )}
            >
              <span className={clsx(
                'w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold',
                step === s.num ? 'bg-white text-primary-600' : 'bg-white/10'
              )}>
                {s.num}
              </span>
              <span>{s.title}</span>
            </button>
          ))}
        </div>

        {/* Error Alert */}
        {error && (
          <div className="p-3.5 rounded-xl bg-red-500/15 border border-red-500/30 text-xs text-red-300 flex items-start gap-2.5">
            <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
            <div className="flex-1">{error}</div>
          </div>
        )}

        {/* ── STEP 1: General Info ────────────────────────────────────────── */}
        {step === 1 && (
          <div className="space-y-4 animate-fade-in">
            <div>
              <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Camera Name *</label>
              <input
                className="input-field"
                placeholder="e.g. Office Entrance Main"
                value={form.name}
                onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
              />
              <span className="text-[10px] text-slate-500 mt-1 block">A clear descriptive name for operator dashboard views.</span>
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Location / Zone *</label>
              <input
                className="input-field"
                placeholder="e.g. Gate A, Server Room, Main Entrance"
                value={form.location}
                onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
              />
            </div>

            <div>
              <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Description (Optional)</label>
              <textarea
                className="input-field py-2 text-xs"
                rows={2}
                placeholder="Optional notes or reference serial number..."
                value={form.description}
                onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
              />
            </div>
          </div>
        )}

        {/* ── STEP 2: Connection Setup ───────────────────────────────────── */}
        {step === 2 && (
          <div className="space-y-4 animate-fade-in">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Camera Brand *</label>
                <select
                  className="input-field custom-select cursor-pointer"
                  value={form.brand}
                  onChange={e => setForm(f => ({ ...f, brand: e.target.value }))}
                >
                  {CAMERA_BRANDS.map(b => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">IP Address *</label>
                <input
                  className="input-field font-mono"
                  placeholder="e.g. 192.168.0.125"
                  value={form.ip_address}
                  onChange={e => setForm(f => ({ ...f, ip_address: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-3 gap-3">
              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">RTSP Port</label>
                <input
                  type="number"
                  className="input-field font-mono"
                  placeholder="554"
                  value={form.port}
                  onChange={e => setForm(f => ({ ...f, port: parseInt(e.target.value) || 554 }))}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Username</label>
                <input
                  className="input-field"
                  placeholder="admin"
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Password</label>
                <input
                  type="password"
                  className="input-field"
                  placeholder="••••••••"
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Channel Number</label>
                <input
                  type="number"
                  className="input-field font-mono"
                  placeholder="1"
                  value={form.channel}
                  onChange={e => setForm(f => ({ ...f, channel: parseInt(e.target.value) || 1 }))}
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-300 mb-1.5 block">Stream Quality</label>
                <select
                  className="input-field custom-select cursor-pointer"
                  value={form.stream_type}
                  onChange={e => setForm(f => ({ ...f, stream_type: e.target.value }))}
                >
                  <option value="sub">Sub Stream (Recommended for AI)</option>
                  <option value="main">Main Stream (High Resolution)</option>
                </select>
              </div>
            </div>

            {/* Rotation & Recognition Toggles */}
            <div className="border-t border-white/10 pt-3 flex items-center justify-between">
              <div>
                <label className="text-xs font-semibold text-slate-300 block mb-1">Rotation Angle</label>
                <div className="flex gap-1.5">
                  {ROTATION_OPTIONS.map(r => (
                    <button
                      key={r}
                      type="button"
                      onClick={() => setForm(f => ({ ...f, rotation: r }))}
                      className={clsx(
                        'px-2.5 py-1 rounded-lg text-xs font-semibold transition-all',
                        form.rotation === r
                          ? 'bg-primary-500 text-white shadow'
                          : 'glass text-slate-400 hover:text-white'
                      )}
                    >
                      {r}°
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setForm(f => ({ ...f, enabled: !f.enabled }))}
                  className={clsx(
                    'w-11 h-6 rounded-full transition-all relative cursor-pointer',
                    form.enabled ? 'bg-green-500' : 'bg-slate-700'
                  )}
                >
                  <span className={clsx(
                    'absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow-md',
                    form.enabled ? 'left-5.5' : 'left-0.5'
                  )} />
                </button>
                <span className="text-xs font-semibold text-slate-300">
                  {form.enabled ? 'AI Enabled' : 'AI Paused'}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* ── STEP 3: Validation & Preview ───────────────────────────────── */}
        {step === 3 && (
          <div className="space-y-4 animate-fade-in">
            <div className="glass rounded-xl p-4 border border-white/10 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h4 className="text-sm font-bold text-white">{form.name || 'Unnamed Camera'}</h4>
                  <p className="text-xs text-slate-400">{form.brand} • {form.ip_address || 'No IP'}:{form.port}</p>
                </div>
                <button
                  onClick={handleTestConnection}
                  disabled={testing}
                  className="btn-primary py-1.5 text-xs disabled:opacity-50"
                >
                  {testing ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                  {testing ? 'Testing...' : 'Test Connection'}
                </button>
              </div>

              {/* Test Result Display */}
              {testResult && (
                <div className="p-3 rounded-lg bg-green-500/15 border border-green-500/30 text-xs text-green-300 space-y-2">
                  <div className="flex items-center justify-between font-semibold">
                    <span className="flex items-center gap-1.5">
                      <CheckCircle className="w-4 h-4 text-green-400" />
                      Stream Connected Successfully
                    </span>
                    <span>{testResult.elapsed_s}s latency</span>
                  </div>
                  {testResult.resolution && (
                    <div className="text-[11px] text-slate-400">Resolution: {testResult.resolution}</div>
                  )}
                  {testResult.preview_b64 && (
                    <img
                      src={testResult.preview_b64}
                      alt="Stream Frame Preview"
                      className="w-full aspect-video rounded-lg object-cover border border-white/10 mt-2"
                    />
                  )}
                </div>
              )}

              {testError && (
                <div className="p-3 rounded-lg bg-red-500/15 border border-red-500/30 text-xs text-red-300 flex items-start gap-2">
                  <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                  <div>{testError}</div>
                </div>
              )}
            </div>

            <div className="text-[11px] text-slate-500">
              When saved, FastAPI will automatically save this configuration to <code className="text-primary-400">cameras.json</code> and start an isolated worker thread.
            </div>
          </div>
        )}

        {/* Wizard Footer Controls */}
        <div className="flex items-center justify-between border-t border-white/10 pt-4">
          {step > 1 ? (
            <button
              onClick={() => setStep((step - 1) as any)}
              className="btn-secondary py-2 text-xs"
            >
              <ArrowLeft className="w-3.5 h-3.5" /> Back
            </button>
          ) : (
            <button onClick={onClose} className="btn-secondary py-2 text-xs">
              Cancel
            </button>
          )}

          {step < 3 ? (
            <button
              onClick={() => {
                if (step === 1 && !form.name) {
                  setError('Please enter a Camera Name.')
                  return
                }
                setError(null)
                setStep((step + 1) as any)
              }}
              className="btn-primary py-2 text-xs"
            >
              Next Step <ArrowRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={saving}
              className="btn-primary py-2 text-xs bg-green-600 hover:bg-green-500 disabled:opacity-50"
            >
              <CheckCircle className="w-3.5 h-3.5" />
              {saving ? 'Saving Camera...' : 'Save & Start Stream'}
            </button>
          )}
        </div>

      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Live Fullscreen Camera Modal
// ─────────────────────────────────────────────────────────────────────────────

function FullscreenPreviewModal({ cam, onClose }: { cam: CameraConfig; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 bg-black/90 backdrop-blur-md flex flex-col p-4 animate-fade-in">
      <div className="flex items-center justify-between mb-3 text-white">
        <div className="flex items-center gap-3">
          <span className="live-dot w-2 h-2" />
          <h3 className="font-bold text-lg">{cam.name}</h3>
          <span className="text-xs text-slate-400">{cam.location} • {cam.brand || 'RTSP'}</span>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-white/10">
          <X className="w-6 h-6" />
        </button>
      </div>
      <div className="flex-1 bg-navy-950 rounded-2xl overflow-hidden relative border border-white/10 flex items-center justify-center">
        <img
          src={getStreamUrl(cam.id || cam.camera_id!)}
          alt={cam.name}
          className="w-full h-full object-contain"
        />
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Cameras Management Page Component
// ─────────────────────────────────────────────────────────────────────────────

export function Cameras() {
  const { cameras, setCameras } = useStore()
  const [loading, setLoading] = useState(true)
  const [wizardCam, setWizardCam] = useState<CameraConfig | 'new' | null>(null)
  const [previewCam, setPreviewCam] = useState<CameraConfig | null>(null)
  const [deleteConfirm, setDeleteConfirm] = useState<CameraConfig | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadCameras = async () => {
    setLoading(true)
    try {
      const data = await getCameras()
      setCameras(data)
    } catch (err) {
      console.error('Failed to load cameras:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadCameras()
    const interval = setInterval(() => {
      getCameras().then(setCameras).catch(() => {})
    }, 10000)
    return () => clearInterval(interval)
  }, [])

  const toggleCameraEnabled = async (cam: CameraConfig) => {
    const camId = cam.id || cam.camera_id!
    const updatedPayload: CameraCreatePayload = {
      id: camId,
      camera_id: camId,
      name: cam.name,
      location: cam.location,
      description: cam.description || '',
      brand: cam.brand || 'Custom',
      ip_address: cam.ip_address || '',
      port: cam.port || 554,
      username: cam.username || '',
      password: cam.password || '',
      channel: cam.channel || 1,
      stream_type: cam.stream_type || 'sub',
      enabled: !cam.enabled,
      rotation: cam.rotation || 0,
      source: cam.source || '',
    }
    try {
      await updateCamera(camId, updatedPayload)
      await loadCameras()
    } catch (err: any) {
      alert(`Failed to toggle camera: ${err.message}`)
    }
  }

  const handleDelete = async (cam: CameraConfig) => {
    setDeleting(true)
    try {
      const camId = cam.id || cam.camera_id!
      await deleteCamera(camId)
      await loadCameras()
      setDeleteConfirm(null)
    } catch (err: any) {
      alert(`Failed to delete camera: ${err.message}`)
    } finally {
      setDeleting(false)
    }
  }


  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Camera Management" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">

        {/* Page Title & Actions */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2.5">
              <CameraIcon className="w-5 h-5 text-blue-500 dark:text-primary-400" />
              CCTV Camera Registry
            </h2>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Backend-managed isolated streams • Auto RTSP generation • Thread-safe buffering
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button onClick={loadCameras} className="btn-secondary py-2 text-xs">
              <RefreshCw className="w-3.5 h-3.5" /> Refresh
            </button>
            <button onClick={() => setWizardCam('new')} className="btn-primary py-2 text-xs">
              <Plus className="w-4 h-4" /> Add Camera
            </button>
          </div>
        </div>

        {/* Camera Cards Grid */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {[1, 2, 3].map(i => <div key={i} className="skeleton h-80 rounded-2xl" />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
            {cameras.map(cam => {
              const camId = cam.id || cam.camera_id!
              const isOnline = cam.enabled

              return (
                <div
                  key={camId}
                  className="glass rounded-2xl overflow-hidden border border-slate-200 dark:border-white/5 hover:border-primary-500/30 transition-all duration-300 flex flex-col group"
                >
                  {/* Live Stream Preview Header */}
                  <div className="relative aspect-video bg-navy-950 overflow-hidden border-b border-slate-200 dark:border-white/5">
                    {isOnline ? (
                      <img
                        src={getStreamUrl(camId)}
                        alt={cam.name}
                        className="video-stream object-cover w-full h-full"
                      />
                    ) : (
                      <div className="flex flex-col items-center justify-center h-full gap-2 text-slate-600">
                        <CameraIcon className="w-10 h-10" />
                        <span className="text-xs font-semibold">Camera Stream Offline</span>
                      </div>
                    )}

                    <div className="cam-overlay" />

                    {/* Status Pill */}
                    <div className="absolute top-3 left-3 flex items-center gap-2">
                      <span className={isOnline ? 'badge-green' : 'badge-red'}>
                        {isOnline ? '● ONLINE' : '○ OFFLINE'}
                      </span>
                      <span className="badge-blue text-[10px]">
                        {cam.brand || 'RTSP'}
                      </span>
                    </div>

                    {/* Quick Action Overlay Buttons */}
                    <div className="absolute top-3 right-3 flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => setPreviewCam(cam)}
                        className="w-8 h-8 rounded-xl bg-black/60 backdrop-blur-sm text-white flex items-center justify-center hover:bg-primary-500 transition-colors"
                        title="Fullscreen Preview"
                      >
                        <Maximize2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  {/* Camera Details */}
                  <div className="p-4 flex-1 flex flex-col justify-between space-y-4">
                    <div>
                      <div className="flex items-start justify-between">
                        <div>
                          <h3 className="font-bold text-slate-900 dark:text-white text-base">{cam.name}</h3>
                          <p className="text-xs text-slate-500 dark:text-slate-400">{cam.location}</p>
                        </div>
                      </div>

                      <div className="mt-3 text-xs font-mono text-slate-600 dark:text-slate-400 bg-slate-100 dark:bg-navy-950 rounded-lg px-3 py-2 border border-slate-200 dark:border-white/5 truncate">
                        {cam.source || `${cam.ip_address || '127.0.0.1'}:${cam.port || 554}`}
                      </div>
                    </div>

                    {/* Recognition Activity & Metadata */}
                    <div className="border-t border-slate-200 dark:border-white/5 pt-3 space-y-2 text-xs text-slate-500 dark:text-slate-400">
                      <div className="flex justify-between">
                        <span>AI Recognition</span>
                        <span className={cam.enabled ? 'text-green-400 font-semibold' : 'text-slate-500'}>
                          {cam.enabled ? 'Active' : 'Paused'}
                        </span>
                      </div>
                      {cam.last_recognition ? (
                        <div className="flex justify-between text-[11px]">
                          <span>Last Seen</span>
                          <span className="text-blue-600 dark:text-primary-400 font-semibold">{cam.last_recognition.name} ({cam.last_recognition.recognized_at})</span>
                        </div>
                      ) : null}
                    </div>

                    {/* Card Actions */}
                    <div className="flex gap-2 border-t border-slate-200 dark:border-white/5 pt-3">
                      <button
                        onClick={() => toggleCameraEnabled(cam)}
                        className={clsx(
                          'py-2 px-3 rounded-xl text-xs font-semibold flex items-center justify-center gap-1.5 transition-all flex-1',
                          cam.enabled
                            ? 'bg-green-500/15 text-green-400 border border-green-500/30 hover:bg-green-500/25'
                            : 'bg-slate-100 dark:bg-slate-700/50 text-slate-600 dark:text-slate-400 border border-slate-300 dark:border-slate-600 hover:text-slate-900 dark:hover:text-white'
                        )}
                      >
                        {cam.enabled ? '● Enabled' : '○ Disabled'}
                      </button>

                      <button
                        onClick={() => setWizardCam(cam)}
                        className="btn-secondary justify-center py-2 text-xs px-3"
                        title="Edit Camera Configuration"
                      >
                        <Edit2 className="w-3.5 h-3.5" /> Edit
                      </button>

                      <button
                        onClick={() => setDeleteConfirm(cam)}
                        className="btn-danger py-2 text-xs px-3"
                        title="Delete Camera"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}


            {/* Add Camera Card */}
            <button
              onClick={() => setWizardCam('new')}
              className="glass rounded-2xl border-2 border-dashed border-slate-200 dark:border-white/10 hover:border-blue-500/40 p-6 flex flex-col items-center justify-center gap-3 text-slate-500 hover:text-blue-500 dark:hover:text-primary-400 transition-all min-h-[300px]"
            >
              <div className="w-12 h-12 rounded-full glass border border-white/10 flex items-center justify-center text-primary-400">
                <Plus className="w-6 h-6" />
              </div>
              <div className="text-center">
                <span className="text-sm font-bold text-slate-200 block">Add New CCTV Camera</span>
                <span className="text-xs text-slate-500">Configure brand, IP & credentials</span>
              </div>
            </button>
          </div>
        )}

      </div>

      {/* Add/Edit Wizard Dialog */}
      {wizardCam && (
        <AddEditCameraWizard
          initial={wizardCam === 'new' ? null : wizardCam}
          onSuccess={loadCameras}
          onClose={() => setWizardCam(null)}
        />
      )}

      {/* Fullscreen Preview Modal */}
      {previewCam && (
        <FullscreenPreviewModal
          cam={previewCam}
          onClose={() => setPreviewCam(null)}
        />
      )}

      {/* Delete Confirmation Modal */}
      {deleteConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in p-4">
          <div className="glass-bright rounded-2xl p-6 w-full max-w-sm border border-red-500/30 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-red-500/15 text-red-400 flex items-center justify-center mx-auto">
              <Trash2 className="w-6 h-6" />
            </div>
            <div>
              <h3 className="font-bold text-white text-base">Delete Camera?</h3>
              <p className="text-xs text-slate-400 mt-1">
                Are you sure you want to delete <strong className="text-white">{deleteConfirm.name}</strong>?
                This will update <code className="text-primary-400">cameras.json</code> and stop the AI worker thread.
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setDeleteConfirm(null)}
                className="btn-secondary flex-1 justify-center text-xs"
              >
                Cancel
              </button>
              <button
                onClick={() => handleDelete(deleteConfirm)}
                disabled={deleting}
                className="btn-danger flex-1 justify-center text-xs bg-red-600 hover:bg-red-500 text-white disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete Camera'}
              </button>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
