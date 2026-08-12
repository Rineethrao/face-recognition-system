import { useEffect, useState } from 'react'
import { GitMerge, X, Save, Images, AlertCircle } from 'lucide-react'
import { getMergePreview, mergeVisitors, BulkPromotePreview } from '../../lib/api'
import { toast } from '../ui/Toast'

interface VisitorMergeModalProps {
  visitorIds: number[]
  visitorCodes: string[]
  primaryVisitorId?: number
  isOpen: boolean
  onClose: () => void
  onSuccess: (primaryVisitorId: number) => void
}

export function VisitorMergeModal({
  visitorIds,
  visitorCodes,
  primaryVisitorId,
  isOpen,
  onClose,
  onSuccess
}: VisitorMergeModalProps) {
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [preview, setPreview] = useState<BulkPromotePreview | null>(null)
  const [primaryId, setPrimaryId] = useState<number>(primaryVisitorId || visitorIds[0])

  useEffect(() => {
    if (!isOpen || visitorIds.length < 2) return
    setPrimaryId(primaryVisitorId || visitorIds[0])
    setLoading(true)
    setPreview(null)
    getMergePreview(visitorIds)
      .then(setPreview)
      .catch((err) => {
        console.error(err)
        toast.error('Preview Failed', err?.response?.data?.detail || 'Could not load merge preview.')
      })
      .finally(() => setLoading(false))
  }, [isOpen, visitorIds.join(','), primaryVisitorId])

  if (!isOpen) return null

  const primaryCode = visitorCodes[visitorIds.indexOf(primaryId)] || preview?.visitors.find(v => v.visitor_id === primaryId)?.visitor_code

  const handleMerge = async () => {
    setSubmitting(true)
    try {
      const res = await mergeVisitors({
        visitor_ids: visitorIds,
        primary_visitor_id: primaryId,
      })
      const data = res.data
      toast.success(
        'Visitors Merged',
        `Combined ${visitorCodes.length} profiles into ${data.primary_visitor_code}. Duplicate IDs are now hidden — tracking continues under one visitor.`
      )
      onSuccess(data.primary_visitor_id)
      onClose()
    } catch (err: any) {
      console.error(err)
      toast.error('Merge Failed', err?.response?.data?.detail || 'Could not merge visitors.')
    } finally {
      setSubmitting(false)
    }
  }

  const absorbedCodes = visitorCodes.filter((_, i) => visitorIds[i] !== primaryId)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto shadow-2xl text-slate-100">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 sticky top-0 bg-slate-950/90 z-10">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-xl bg-violet-500/10 text-violet-400 border border-violet-500/20">
              <GitMerge className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-semibold text-lg text-white">Merge Duplicate Visitors</h3>
              <p className="text-xs text-slate-400">Combine into one profile for tracking (not registration)</p>
            </div>
          </div>
          <button onClick={onClose} className="p-1 text-slate-400 hover:text-white rounded-lg">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="p-6 space-y-5">
          <div className="p-4 rounded-xl bg-violet-500/10 border border-violet-500/30 text-sm">
            <p className="text-violet-200">
              <strong>{absorbedCodes.join(', ')}</strong> will be absorbed into{' '}
              <strong>{primaryCode || 'primary visitor'}</strong>.
            </p>
            <p className="text-violet-200/70 text-xs mt-2">
              All face photos, sightings, and timeline events move to the primary ID. Duplicate visitor rows disappear from the list but history is preserved.
            </p>
          </div>

          {preview && preview.pairwise_similarities.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {preview.pairwise_similarities.map((pair) => (
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
          )}

          <div className="space-y-2">
            <label className="text-xs font-medium text-slate-400">Keep as primary tracking ID</label>
            <select
              value={primaryId}
              onChange={(e) => setPrimaryId(Number(e.target.value))}
              className="w-full px-3 py-2 bg-slate-950 border border-slate-800 rounded-xl text-sm text-white"
            >
              {visitorIds.map((id, i) => (
                <option key={id} value={id}>{visitorCodes[i]}</option>
              ))}
            </select>
            <p className="text-xs text-slate-500">Cameras will recognize this person under the primary visitor code going forward.</p>
          </div>

          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <Images className="w-4 h-4 text-cyan-400" />
              <h4 className="text-sm font-semibold text-slate-200">Combined face photos</h4>
            </div>
            {loading ? (
              <div className="text-xs text-slate-500 py-6 text-center border border-dashed border-slate-800 rounded-xl">
                Loading photos...
              </div>
            ) : preview ? (
              <div className="space-y-4">
                {preview.visitors.map((v) => (
                  <div key={v.visitor_id} className="space-y-2">
                    <p className={`text-xs font-semibold uppercase tracking-wide ${
                      v.visitor_id === primaryId ? 'text-violet-300' : 'text-slate-400'
                    }`}>
                      {v.visitor_code} {v.visitor_id === primaryId ? '(primary — kept)' : '(will merge in)'}
                    </p>
                    <div className="grid grid-cols-4 gap-2">
                      {v.samples.slice(0, 4).map((s) => (
                        <img
                          key={s.id}
                          src={s.snapshot_url || v.primary_snapshot_url}
                          alt=""
                          className="w-full aspect-square object-cover rounded-lg border border-slate-700"
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          {preview && preview.min_pairwise_similarity < 0.48 && (
            <div className="flex gap-2 p-3 rounded-xl bg-amber-500/10 border border-amber-500/30 text-xs text-amber-200">
              <AlertCircle className="w-4 h-4 shrink-0" />
              Face similarity is low — please confirm visually these are the same person before merging.
            </div>
          )}

          <div className="flex justify-end gap-3 pt-4 border-t border-slate-800">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-sm text-slate-400 hover:text-white hover:bg-slate-800"
            >
              Cancel
            </button>
            <button
              onClick={handleMerge}
              disabled={submitting || loading}
              className="flex items-center gap-2 px-5 py-2 rounded-xl text-sm font-medium bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-400 hover:to-purple-500 text-white disabled:opacity-50"
            >
              <Save className="w-4 h-4" />
              {submitting ? 'Merging...' : `Merge into ${primaryCode}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
