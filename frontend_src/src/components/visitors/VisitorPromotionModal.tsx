import { useEffect, useState } from 'react'
import { UserCheck, X, Save, AlertCircle, Images, UserPlus, ArrowRight, Users } from 'lucide-react'
import {
  getPromotePreview,
  getBulkPromotePreview,
  promoteVisitor,
  bulkPromoteVisitors,
  PromotePreview,
  BulkPromotePreview,
  PromotePreviewMatchedPerson,
} from '../../lib/api'
import { toast } from '../ui/Toast'

interface VisitorPromotionModalProps {
  visitorIds: number[]
  visitorCodes: string[]
  primarySnapshotUrl?: string
  isOpen: boolean
  onClose: () => void
  onSuccess: () => void
}

const ROLE_OPTIONS = [
  'Employee',
  'Staff',
  'Contractor',
  'Security',
  'VIP',
  'Visitor',
  'Watchlist',
  'Blacklist'
]

type PreviewState = (PromotePreview | BulkPromotePreview) & { isBulk?: boolean }

function sanitizeName(value?: string | null) {
  if (!value || value.trim() === '*' || value.trim() === '-') return ''
  return value.trim()
}

function parseDuplicateError(detail: string): PromotePreviewMatchedPerson | null {
  const match = detail.match(
    /(?:already matches|already match) registered person '([^']+)' \(([^)]+)\) at ([\d.]+)%/i
  )
  if (!match) return null
  const [, name, person_id, simPct] = match
  const parts = name.trim().split(/\s+/)
  return {
    person_id,
    name,
    similarity: parseFloat(simPct) / 100,
    match_level: 'hard',
    first_name: parts[0] || '',
    last_name: parts.slice(1).join(' '),
    existing_images: [],
    existing_image_count: 0,
  }
}

function isBulkPreview(p: PreviewState | null): p is BulkPromotePreview {
  return Boolean(p && 'visitor_count' in p && (p as BulkPromotePreview).visitor_count > 1)
}

export function VisitorPromotionModal({
  visitorIds,
  visitorCodes,
  primarySnapshotUrl,
  isOpen,
  onClose,
  onSuccess
}: VisitorPromotionModalProps) {
  const isBulk = visitorIds.length > 1
  const codesLabel = visitorCodes.join(', ')

  const [submitting, setSubmitting] = useState(false)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [preview, setPreview] = useState<PreviewState | null>(null)
  const [forcedMatch, setForcedMatch] = useState<PromotePreviewMatchedPerson | null>(null)
  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    department: '',
    role: 'Employee',
    phone: '',
    email: '',
    notes: ''
  })

  const applyMatchedForm = (match: PromotePreviewMatchedPerson) => {
    setForm((prev) => ({
      ...prev,
      first_name: sanitizeName(match.first_name) || prev.first_name,
      last_name: sanitizeName(match.last_name) || prev.last_name,
      department: match.department || prev.department,
      role: match.role || prev.role,
      phone: match.phone || prev.phone,
      email: match.email || prev.email,
    }))
  }

  const loadPreview = () => {
    setLoadingPreview(true)
    const loader = isBulk
      ? getBulkPromotePreview(visitorIds).then((data) => {
          setPreview(data)
          if (data.matched_registered_person) applyMatchedForm(data.matched_registered_person)
        })
      : getPromotePreview(visitorIds[0]).then((data) => {
          setPreview(data)
          if (data.matched_registered_person) applyMatchedForm(data.matched_registered_person)
        })

    return loader
      .catch((err) => {
        console.error(err)
        toast.error('Preview Failed', err?.response?.data?.detail || 'Could not load registration preview.')
      })
      .finally(() => setLoadingPreview(false))
  }

  useEffect(() => {
    if (!isOpen || visitorIds.length === 0) return
    setPreview(null)
    setForcedMatch(null)
    setForm({
      first_name: '',
      last_name: '',
      department: '',
      role: 'Employee',
      phone: '',
      email: '',
      notes: ''
    })
    loadPreview()
  }, [isOpen, visitorIds.join(',')])

  if (!isOpen) return null

  const matched = forcedMatch || preview?.matched_registered_person
  const isMergeMode = Boolean(matched && (preview?.can_merge_existing || forcedMatch))
  const bulkPreview = isBulkPreview(preview) ? preview : null

  const handleSubmit = async (e: React.FormEvent, forceMerge = false) => {
    e.preventDefault()
    if (!form.first_name.trim() || !form.last_name.trim()) {
      toast.error('Validation Error', 'First name and last name are required.')
      return
    }

    const payload = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim(),
      department: form.department.trim() || undefined,
      role: form.role,
      phone: form.phone.trim() || undefined,
      email: form.email.trim() || undefined,
      notes: form.notes.trim() || undefined,
      merge_into_existing: forceMerge || isMergeMode,
      target_person_id: matched?.person_id,
    }

    setSubmitting(true)
    try {
      if (isBulk) {
        await bulkPromoteVisitors({
          visitor_ids: visitorIds,
          primary_visitor_id: visitorIds[0],
          ...payload,
        })
      } else {
        await promoteVisitor(visitorIds[0], payload)
      }

      const sampleCount = preview?.sample_count || 0
      if (forceMerge || isMergeMode) {
        toast.success(
          'Profile Updated',
          `Added ${sampleCount} face photo(s) from ${codesLabel} to existing profile '${matched?.name}'.`
        )
      } else if (isBulk) {
        toast.success(
          'Visitors Merged & Registered',
          `Registered ${visitorIds.length} duplicate visitors (${codesLabel}) as '${form.first_name} ${form.last_name}' with ${sampleCount} face photo(s).`
        )
      } else {
        toast.success(
          'Person Registered',
          `Registered ${codesLabel} as '${form.first_name} ${form.last_name}' with ${sampleCount} face photo(s).`
        )
      }
      onSuccess()
      onClose()
    } catch (err: any) {
      console.error(err)
      const detail = err?.response?.data?.detail || 'Failed to register visitor as person.'
      const parsed = parseDuplicateError(detail)
      if (parsed && !forcedMatch) {
        setForcedMatch(parsed)
        applyMatchedForm(parsed)
        loadPreview()
        toast.error(
          'Duplicate Detected',
          `${detail} Use the green "Add Photos" button below to merge all selected visitors into the existing profile.`
        )
      } else {
        toast.error('Registration Failed', detail)
      }
    } finally {
      setSubmitting(false)
    }
  }

  const visitorSamples = preview?.samples_to_transfer || []
  const existingImages = matched?.existing_images || []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4 animate-in fade-in duration-200">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-3xl max-h-[90vh] overflow-y-auto shadow-2xl text-slate-100">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/50 sticky top-0 z-10">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
              {isBulk ? <Users className="w-5 h-5" /> : <UserCheck className="w-5 h-5" />}
            </div>
            <div>
              <h3 className="font-semibold text-lg text-white">
                {isBulk
                  ? isMergeMode
                    ? 'Add Duplicate Visitors to Profile'
                    : 'Merge Duplicate Visitors'
                  : isMergeMode
                    ? 'Add Photos to Existing Profile'
                    : 'Register Visitor'}
              </h3>
              <p className="text-xs text-slate-400">
                {isBulk
                  ? `Combine ${visitorIds.length} visitor profiles into one registered person`
                  : isMergeMode
                    ? `Transfer face photos from ${codesLabel} into registered profile`
                    : `Promote ${codesLabel} to Registered Person`}
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 text-slate-400 hover:text-white hover:bg-slate-800 rounded-lg transition-colors"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <form onSubmit={(e) => handleSubmit(e, isMergeMode)} className="p-6 space-y-5">
          {isBulk && bulkPreview && (
            <div className="p-4 rounded-xl bg-violet-500/10 border border-violet-500/30 space-y-2">
              <p className="text-sm font-medium text-violet-300">
                Merging: {visitorCodes.join(' + ')}
              </p>
              <div className="flex flex-wrap gap-2">
                {bulkPreview.pairwise_similarities.map((pair) => (
                  <span
                    key={`${pair.visitor_a_id}-${pair.visitor_b_id}`}
                    className={`text-[11px] px-2 py-1 rounded-lg border ${
                      pair.same_person_likely
                        ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                        : 'bg-slate-800 text-slate-400 border-slate-700'
                    }`}
                  >
                    {pair.visitor_a_code} ↔ {pair.visitor_b_code}: {(pair.similarity * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
              <p className="text-xs text-violet-200/70">
                {bulkPreview.min_pairwise_similarity >= 0.48
                  ? 'Face similarity confirms these are likely the same person.'
                  : 'Review photos below — similarity is lower than usual, confirm visually before registering.'}
              </p>
            </div>
          )}

          {matched && (
            <div className="flex gap-3 p-4 rounded-xl bg-amber-500/10 border border-amber-500/30">
              <AlertCircle className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
              <div className="text-sm">
                <p className="font-medium text-amber-300">
                  {isMergeMode ? 'Matches existing profile:' : 'Possible match:'} {matched.name}
                </p>
                <p className="text-amber-200/80 text-xs mt-1">
                  Similarity {(matched.similarity * 100).toFixed(1)}% —{' '}
                  {isMergeMode
                    ? 'review photos below, then add all selected visitor snapshots to the existing gallery.'
                    : 'you can still register as new, or merge if this is the same person.'}
                </p>
              </div>
            </div>
          )}

          <div className={`grid gap-4 ${isMergeMode && existingImages.length > 0 ? 'md:grid-cols-[1fr_auto_1fr]' : 'grid-cols-1'}`}>
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Images className="w-4 h-4 text-cyan-400" />
                <h4 className="text-sm font-semibold text-slate-200">
                  Visitor photos to {isMergeMode ? 'add' : 'register'} ({visitorSamples.length})
                </h4>
              </div>
              {loadingPreview ? (
                <div className="text-xs text-slate-500 py-8 text-center border border-dashed border-slate-800 rounded-xl">
                  Loading face samples...
                </div>
              ) : visitorSamples.length === 0 ? (
                <div className="text-xs text-slate-500 py-8 text-center border border-dashed border-slate-800 rounded-xl">
                  No face samples available yet. Wait for clearer captures before registering.
                </div>
              ) : isBulk && bulkPreview ? (
                <div className="space-y-4">
                  {bulkPreview.visitors.map((v) => (
                    <div key={v.visitor_id} className="space-y-2">
                      <p className="text-xs font-semibold text-cyan-300/90 uppercase tracking-wide">
                        {v.visitor_code} ({v.sample_count} photos)
                      </p>
                      <div className="grid grid-cols-3 gap-2">
                        {v.samples.map((s) => (
                          <div key={s.id} className="relative">
                            <img
                              src={s.snapshot_url || v.primary_snapshot_url}
                              alt={`${v.visitor_code}-${s.id}`}
                              className="w-full aspect-square object-cover rounded-lg border-2 border-cyan-600/40"
                            />
                            <div className="absolute bottom-0 inset-x-0 bg-black/75 text-[10px] px-1 py-0.5 rounded-b-lg text-center text-cyan-200">
                              Q {(s.quality_score * 100).toFixed(0)}%
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="grid grid-cols-3 gap-2">
                  {visitorSamples.map((s) => (
                    <div key={s.id} className="relative group">
                      <img
                        src={s.snapshot_url || primarySnapshotUrl}
                        alt={`visitor-sample-${s.id}`}
                        className="w-full aspect-square object-cover rounded-lg border-2 border-cyan-600/40"
                      />
                      <div className="absolute bottom-0 inset-x-0 bg-black/75 text-[10px] px-1 py-0.5 rounded-b-lg text-center text-cyan-200">
                        Q {(s.quality_score * 100).toFixed(0)}%
                      </div>
                    </div>
                  ))}
                </div>
              )}
              <p className="text-xs text-slate-500">
                Best-quality snapshots from all selected visitors will be copied into one permanent registered gallery.
              </p>
            </div>

            {isMergeMode && existingImages.length > 0 && (
              <>
                <div className="hidden md:flex items-center justify-center text-slate-600">
                  <ArrowRight className="w-6 h-6" />
                </div>
                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <UserPlus className="w-4 h-4 text-emerald-400" />
                    <h4 className="text-sm font-semibold text-slate-200">
                      Existing profile photos ({matched?.existing_image_count ?? existingImages.length})
                    </h4>
                  </div>
                  <div className="grid grid-cols-3 gap-2">
                    {existingImages.map((img) => (
                      <div key={img.id} className="relative">
                        <img
                          src={img.image_url}
                          alt={`existing-${img.id}`}
                          className="w-full aspect-square object-cover rounded-lg border-2 border-emerald-600/40"
                        />
                        <div className="absolute bottom-0 inset-x-0 bg-black/75 text-[10px] px-1 py-0.5 rounded-b-lg text-center text-emerald-300">
                          Existing
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </>
            )}
          </div>

          {!isMergeMode && visitorSamples.length > 0 && (
            <div className="p-3 rounded-xl bg-cyan-500/5 border border-cyan-500/20 text-xs text-cyan-200/80">
              {isBulk
                ? `This will create ONE registered person from ${visitorIds.length} duplicate visitor IDs, using ${visitorSamples.length} best face photos combined.`
                : `Registering will create a new profile with ${visitorSamples.length} face photo${visitorSamples.length === 1 ? '' : 's'} shown above.`}
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">First Name *</label>
              <input
                type="text"
                required
                value={form.first_name}
                onChange={e => setForm({ ...form, first_name: e.target.value })}
                placeholder="e.g. John"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Last Name *</label>
              <input
                type="text"
                required
                value={form.last_name}
                onChange={e => setForm({ ...form, last_name: e.target.value })}
                placeholder="e.g. Smith"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Department</label>
              <input
                type="text"
                value={form.department}
                onChange={e => setForm({ ...form, department: e.target.value })}
                placeholder="e.g. Operations"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Role</label>
              <select
                value={form.role}
                onChange={e => setForm({ ...form, role: e.target.value })}
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              >
                {ROLE_OPTIONS.map(r => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Phone</label>
              <input
                type="text"
                value={form.phone}
                onChange={e => setForm({ ...form, phone: e.target.value })}
                placeholder="+1 555-0199"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-400 mb-1">Email</label>
              <input
                type="email"
                value={form.email}
                onChange={e => setForm({ ...form, email: e.target.value })}
                placeholder="john@company.com"
                className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Notes</label>
            <textarea
              rows={2}
              value={form.notes}
              onChange={e => setForm({ ...form, notes: e.target.value })}
              placeholder="Additional notes or employee ID..."
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white focus:outline-none focus:border-cyan-500 resize-none"
            />
          </div>

          <div className="flex items-center justify-end gap-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm font-medium text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
            >
              Cancel
            </button>
            {isMergeMode ? (
              <button
                type="submit"
                disabled={submitting || loadingPreview}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-400 hover:to-teal-500 text-white shadow-lg shadow-emerald-500/20 disabled:opacity-50 transition-all"
              >
                <Save className="w-4 h-4" />
                {submitting
                  ? 'Adding Photos...'
                  : isBulk
                    ? `Add ${visitorSamples.length} Photo(s) to ${matched?.name}`
                    : `Add ${visitorSamples.length} Photo(s) to ${matched?.name}`}
              </button>
            ) : (
              <button
                type="submit"
                disabled={submitting || loadingPreview || visitorSamples.length === 0}
                className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-400 hover:to-blue-500 text-white shadow-lg shadow-cyan-500/20 disabled:opacity-50 transition-all"
              >
                <Save className="w-4 h-4" />
                {submitting
                  ? 'Registering...'
                  : isBulk
                    ? `Register ${visitorIds.length} as One Person (${visitorSamples.length} photos)`
                    : `Register with ${visitorSamples.length} Photo(s)`}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}
