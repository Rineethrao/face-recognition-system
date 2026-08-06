import React from 'react'
import { Sparkles, CheckCircle2, AlertCircle, Clock, ShieldCheck, Compass } from 'lucide-react'
import clsx from 'clsx'

interface AiAssistantProps {
  faceDetected: boolean
  centered: boolean
  sharp: boolean
  lighting: boolean
  eyesVisible: boolean
  faceSizeOk?: boolean
  identityVerified?: boolean
  currentPose?: string
  nextNeededPose?: string
  guidanceText?: string
  statusMessage?: string
  samplesCollected: number
  targetSamples: number
  progressPercent: number
  qualityScore?: number
  state?: string
  poseCoverage?: Record<string, boolean>
  target?: {
    camera_id: string | null
    visible: boolean
    thumbnail?: string
    identity_verified: boolean
  } | null
  onChangeTarget?: () => void
}

export function AiAssistantPanel({
  faceDetected,
  centered,
  sharp,
  lighting,
  eyesVisible,
  faceSizeOk = false,
  identityVerified = false,
  currentPose = 'FRONTAL',
  nextNeededPose,
  guidanceText = 'Click a face to begin registration',
  statusMessage = 'Initializing AI Guidance System...',
  samplesCollected,
  targetSamples,
  progressPercent,
  qualityScore = 0.0,
  state,
  poseCoverage,
  target,
  onChangeTarget
}: AiAssistantProps) {
  const remainingSamples = Math.max(0, targetSamples - samplesCollected)
  const estSeconds = Math.ceil(remainingSamples * 1.2)

  const isWaiting = !state || state === 'WAITING_FOR_SELECTION' || state === 'WAITING_FOR_TARGET'
  const isLost = state === 'TARGET_LOST' || state === 'TARGET_TEMPORARILY_LOST'
  const isReady = state === 'READY_FOR_REVIEW'
  const targetLabel = isWaiting ? 'No face selected' : isLost ? 'Target temporarily lost' : 'Target selected'
  const captureState = isWaiting ? 'Waiting for target' : isLost ? 'Auto capture paused' : 'Auto capture active'

  const checks = [
    { label: 'Face detected', ok: faceDetected },
    { label: 'Face size', ok: faceSizeOk || centered },
    { label: 'Sharp image', ok: sharp },
    { label: 'Good lighting', ok: lighting },
    { label: 'Eyes / landmarks', ok: eyesVisible },
    { label: 'Identity verified', ok: identityVerified },
  ]

  const defaultCoverage = {
    FRONTAL: false,
    SLIGHT_LEFT: false,
    SLIGHT_RIGHT: false,
  }
  const coverage = { ...defaultCoverage, ...(poseCoverage || {}) }

  return (
    <div className="w-full bg-slate-900/90 border border-slate-800 rounded-2xl p-5 shadow-2xl backdrop-blur-xl flex flex-col justify-between space-y-5">
      <div className="flex items-center justify-between border-b border-slate-800/80 pb-3">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-lg bg-blue-600/20 border border-blue-500/30 flex items-center justify-center text-blue-400">
            <Sparkles className="w-4 h-4 animate-pulse" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-white tracking-wide">AI Registration Assistant</h3>
            <p className="text-[11px] text-slate-400">Face quality & pose guidance</p>
          </div>
        </div>
        {qualityScore > 0 && (
          <div className="px-2.5 py-1 rounded-full bg-slate-800 border border-slate-700 text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            {(qualityScore * 100).toFixed(0)}%
          </div>
        )}
      </div>

      {state && (
        <div className={clsx(
          'border rounded-xl p-3 flex flex-col gap-2 transition-all duration-200',
          isWaiting
            ? 'bg-amber-500/5 border-amber-500/20'
            : isLost
            ? 'bg-rose-500/5 border-rose-500/20 shadow-md'
            : isReady
            ? 'bg-blue-500/5 border-blue-500/25'
            : 'bg-emerald-500/5 border-emerald-500/20 shadow-md'
        )}>
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-bold text-slate-400 uppercase tracking-wider">
              Registration Target
            </span>
            <div className="flex items-center gap-1.5">
              {isWaiting ? (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20">
                  Waiting
                </span>
              ) : isLost ? (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-rose-500/10 text-rose-400 border border-rose-500/20 animate-pulse">
                  Paused
                </span>
              ) : isReady ? (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-500/10 text-blue-300 border border-blue-500/20">
                  Ready
                </span>
              ) : (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                  Locked
                </span>
              )}
              {onChangeTarget && !isWaiting && (
                <button
                  onClick={onChangeTarget}
                  className="px-2 py-0.5 rounded text-[10px] font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition-colors cursor-pointer"
                >
                  Change face
                </button>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px]">
            <div className="rounded-lg bg-slate-950/60 border border-slate-800 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Target</div>
              <div className="mt-1 font-semibold text-slate-200">{targetLabel}</div>
            </div>
            <div className="rounded-lg bg-slate-950/60 border border-slate-800 px-2.5 py-2">
              <div className="text-[10px] uppercase tracking-wide text-slate-500">Capture state</div>
              <div className="mt-1 font-semibold text-slate-200">{captureState}</div>
            </div>
          </div>

          {!isWaiting && target && (
            <div className="flex items-center gap-3">
              {target.thumbnail ? (
                <img
                  src={target.thumbnail}
                  alt="Selected face"
                  className="w-12 h-12 rounded-lg object-cover border border-slate-700 shadow bg-slate-950"
                />
              ) : (
                <div className="w-12 h-12 rounded-lg bg-slate-950 border border-slate-800 flex items-center justify-center text-slate-500 text-[10px] font-bold">
                  FACE
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-xs font-bold text-slate-200 truncate">
                  Selected face{target.camera_id ? ` · ${target.camera_id}` : ''}
                </div>
                <div className="flex items-center gap-1.5 text-[10px] text-slate-400 mt-0.5">
                  <span className="font-semibold text-slate-300">Auto capture:</span>
                  {isLost ? (
                    <span className="text-rose-400 font-bold uppercase tracking-wider text-[9px]">Paused</span>
                  ) : (
                    <span className="text-emerald-400 font-bold uppercase tracking-wider text-[9px] animate-pulse">Active</span>
                  )}
                </div>
              </div>
            </div>
          )}

          {isWaiting && (
            <p className="text-[11px] text-amber-300 leading-snug">
              Click the face of the person you want to register in the CCTV view.
            </p>
          )}
          {isLost && (
            <p className="text-[11px] text-rose-300 leading-snug">
              Target temporarily lost. Waiting for the selected face to reappear — capture paused.
            </p>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-2.5">
        {checks.map((c, i) => (
          <div
            key={i}
            className={clsx(
              'flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold transition-all border',
              c.ok
                ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-300'
                : 'bg-slate-800/40 border-slate-800 text-slate-400'
            )}
          >
            {c.ok ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-amber-400/80 shrink-0" />
            )}
            <span className="truncate">{c.label}</span>
          </div>
        ))}
      </div>

      {state && !isWaiting && (
        <div className="bg-slate-800/40 border border-slate-700/60 rounded-xl p-3 space-y-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-400 font-bold">Pose coverage</div>
          <div className="grid grid-cols-3 gap-2">
            {[
              { key: 'FRONTAL' as const, label: 'Frontal' },
              { key: 'SLIGHT_LEFT' as const, label: 'Left' },
              { key: 'SLIGHT_RIGHT' as const, label: 'Right' },
            ].map((p) => (
              <div
                key={p.key}
                className={clsx(
                  'text-center px-2 py-1.5 rounded-lg text-[11px] font-semibold border',
                  coverage[p.key]
                    ? 'bg-emerald-500/10 border-emerald-500/25 text-emerald-300'
                    : 'bg-slate-900/60 border-slate-700 text-slate-500'
                )}
              >
                {coverage[p.key] ? '✓ ' : '○ '}{p.label}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-slate-800/60 border border-slate-700/80 rounded-xl p-3.5 flex items-start gap-3">
        <div className="w-7 h-7 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shrink-0 mt-0.5">
          <Compass className="w-4 h-4" />
        </div>
        <div>
          <div className="text-[11px] uppercase tracking-wider text-amber-400 font-bold">
            {nextNeededPose ? `Next: ${nextNeededPose.replace(/_/g, ' ')}` : 'Instructions'}
          </div>
          <div className="text-xs font-medium text-slate-200 mt-0.5 leading-snug">
            {guidanceText}
          </div>
        </div>
      </div>

      <div className="space-y-2 pt-1 border-t border-slate-800/80">
        <div className="flex items-center justify-between text-xs font-semibold">
          <span className="text-slate-300">Capture progress</span>
          <span className="text-blue-400 font-bold">{progressPercent}%</span>
        </div>

        <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden p-0.5 border border-slate-700/50">
          <div
            className="h-full bg-gradient-to-r from-blue-600 via-indigo-500 to-emerald-400 rounded-full transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>

        <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1">
          <span>{samplesCollected} of {targetSamples} quality samples</span>
          <span className="flex items-center gap-1 text-slate-400">
            <Clock className="w-3 h-3 text-slate-500" />
            {remainingSamples === 0 ? 'Done' : `~${estSeconds}s remaining`}
          </span>
        </div>
      </div>

      <div className="text-center text-xs font-medium text-slate-300 bg-slate-950/40 border border-slate-800 rounded-xl py-2 px-3 truncate">
        {statusMessage}
      </div>
    </div>
  )
}
