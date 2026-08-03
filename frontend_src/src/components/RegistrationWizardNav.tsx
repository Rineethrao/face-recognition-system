import React from 'react'
import { Check, User, Camera, Image, Cpu, CheckCircle } from 'lucide-react'
import clsx from 'clsx'

interface Step {
  id: number
  title: string
  subtitle: string
  icon: React.ElementType
}

const STEPS: Step[] = [
  { id: 1, title: 'Person Info', subtitle: 'Metadata & Profile', icon: User },
  { id: 2, title: 'Capture Method', subtitle: 'Webcam or CCTV', icon: Camera },
  { id: 3, title: 'Face Capture', subtitle: 'AI Guided Acquisition', icon: Cpu },
  { id: 4, title: 'Review Gallery', subtitle: 'Quality & Pose Verification', icon: Image },
  { id: 5, title: 'Processing', subtitle: 'Embedding & FAISS Commit', icon: CheckCircle },
]

interface Props {
  currentStep: number
  onStepClick?: (stepId: number) => void
}

export function RegistrationWizardNav({ currentStep, onStepClick }: Props) {
  return (
    <div className="w-full bg-slate-900/60 backdrop-blur-md border border-slate-800 rounded-2xl p-4 mb-6 shadow-xl">
      <div className="flex items-center justify-between max-w-5xl mx-auto px-2">
        {STEPS.map((step, idx) => {
          const isCompleted = currentStep > step.id
          const isActive = currentStep === step.id
          const Icon = step.icon

          return (
            <React.Fragment key={step.id}>
              {/* Step Item */}
              <div
                onClick={() => isCompleted && onStepClick && onStepClick(step.id)}
                className={clsx(
                  'flex items-center gap-3 transition-all cursor-default select-none',
                  isCompleted && 'cursor-pointer group'
                )}
              >
                <div
                  className={clsx(
                    'w-10 h-10 rounded-xl flex items-center justify-center font-bold text-sm transition-all shadow-md',
                    isCompleted && 'bg-emerald-500 text-white shadow-emerald-500/20 group-hover:scale-105',
                    isActive && 'bg-blue-600 text-white shadow-blue-500/30 ring-4 ring-blue-500/20 scale-105',
                    !isCompleted && !isActive && 'bg-slate-800 text-slate-400 border border-slate-700'
                  )}
                >
                  {isCompleted ? <Check className="w-5 h-5 stroke-[3]" /> : <Icon className="w-5 h-5" />}
                </div>

                <div className="hidden md:block">
                  <div
                    className={clsx(
                      'text-xs font-semibold tracking-wide uppercase',
                      isActive && 'text-blue-400',
                      isCompleted && 'text-emerald-400',
                      !isActive && !isCompleted && 'text-slate-400'
                    )}
                  >
                    Step 0{step.id}
                  </div>
                  <div className="text-sm font-bold text-slate-100">{step.title}</div>
                </div>
              </div>

              {/* Connector Line */}
              {idx < STEPS.length - 1 && (
                <div
                  className={clsx(
                    'flex-1 h-0.5 mx-3 rounded-full transition-all',
                    currentStep > step.id ? 'bg-emerald-500/60' : 'bg-slate-800'
                  )}
                />
              )}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}
