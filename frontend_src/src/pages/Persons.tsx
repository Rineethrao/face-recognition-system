import { useEffect, useState } from 'react'
import { Search, Trash2, User, RefreshCw, Pencil, X, Save } from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { getPersons, deletePerson, updatePerson } from '../lib/api'
import type { Person } from '../lib/api'
import { toast } from '../components/ui/Toast'
import { formatLocalDateTime } from '../lib/datetime'
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

export function Persons() {
  const [persons, setPersons] = useState<Person[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Person | null>(null)
  const [saving, setSaving] = useState(false)
  const [form, setForm] = useState({
    first_name: '',
    last_name: '',
    department: '',
    role: 'Employee',
    phone: '',
    email: '',
    notes: '',
  })

  const loadPersons = async () => {
    setLoading(true)
    try {
      const data = await getPersons()
      setPersons(data)
    } catch (e) {
      console.error(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPersons()
  }, [])

  const openEdit = (p: Person) => {
    const parts = (p.name || '').trim().split(/\s+/)
    setEditing(p)
    setForm({
      first_name: p.first_name || parts[0] || '',
      last_name: p.last_name || parts.slice(1).join(' ') || '',
      department: p.department || '',
      role: p.role || 'Employee',
      phone: p.phone || '',
      email: p.email || '',
      notes: p.notes || '',
    })
  }

  const handleSave = async () => {
    if (!editing) return
    if (!form.first_name.trim() && !form.last_name.trim()) {
      toast.error('Name required', 'Please enter at least a first or last name.')
      return
    }
    setSaving(true)
    try {
      const res = await updatePerson(editing.person_id, {
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim(),
        department: form.department.trim(),
        role: form.role,
        phone: form.phone.trim(),
        email: form.email.trim(),
        notes: form.notes.trim(),
      })
      const updated = res?.data
      setPersons(prev =>
        prev.map(p =>
          p.person_id === editing.person_id
            ? {
                ...p,
                name: updated?.name || `${form.first_name} ${form.last_name}`.trim(),
                first_name: updated?.first_name ?? form.first_name,
                last_name: updated?.last_name ?? form.last_name,
                department: updated?.department ?? form.department,
                role: updated?.role ?? form.role,
                phone: updated?.phone ?? form.phone,
                email: updated?.email ?? form.email,
                notes: updated?.notes ?? form.notes,
              }
            : p
        )
      )
      toast.success('Person updated', 'Details saved successfully.')
      setEditing(null)
    } catch (e: any) {
      toast.error('Update failed', e?.response?.data?.detail || e.message || 'Could not save changes')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete ${name} (${id})?`)) return
    try {
      await deletePerson(id)
      setPersons(prev => prev.filter(p => p.person_id !== id))
      toast.success('Deleted', `${name} removed.`)
    } catch (e) {
      alert('Failed to delete person')
    }
  }

  const filtered = persons.filter(p =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.person_id.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <TopBar title="Registered Persons" />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="flex items-center justify-between gap-4">
          <div className="relative flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              className="input-field pl-9"
              placeholder="Search by name or ID..."
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>

          <button onClick={loadPersons} className="btn-secondary">
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
        </div>

        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {[1, 2, 3, 4].map(i => <div key={i} className="skeleton h-48 rounded-2xl" />)}
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
            {filtered.map(p => (
              <div key={p.person_id} className="glass rounded-2xl p-4 border border-slate-200 dark:border-white/5 hover:border-primary-500/20 transition-all flex flex-col justify-between">
                <div>
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <div className="flex items-center gap-3 min-w-0">
                      {p.face_images && p.face_images.length > 0 ? (
                        <img src={p.face_images[0]} alt={p.name} className="w-12 h-12 rounded-xl object-cover border border-slate-200 dark:border-white/10 flex-shrink-0" />
                      ) : (
                        <div className="w-12 h-12 rounded-xl bg-primary-500/15 text-primary-400 flex items-center justify-center font-bold flex-shrink-0">
                          <User className="w-6 h-6" />
                        </div>
                      )}
                      <div className="min-w-0">
                        <h3 className="font-semibold text-slate-900 dark:text-white text-sm line-clamp-1">{p.name}</h3>
                        <p className="text-xs text-blue-600 dark:text-primary-400 font-mono">ID: {p.person_id}</p>
                        {(p.department || p.role) && (
                          <p className="text-[10px] text-slate-500 mt-0.5 truncate">
                            {[p.role, p.department].filter(Boolean).join(' · ')}
                          </p>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-0.5 flex-shrink-0">
                      <button
                        onClick={() => openEdit(p)}
                        className="text-slate-500 hover:text-blue-400 p-1.5 rounded-lg hover:bg-blue-500/10 transition-colors"
                        title="Edit Person"
                      >
                        <Pencil className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(p.person_id, p.name)}
                        className="text-slate-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors"
                        title="Delete Person"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>

                  <div className="text-xs text-slate-500 dark:text-slate-400 space-y-1 mb-3">
                    <div className="flex items-center justify-between">
                      <span>Sample Embeddings</span>
                      <span className="badge-blue text-[10px]">{p.embedding_count}</span>
                    </div>
                    <div className="text-[10px] text-slate-500">Registered: {formatLocalDateTime(p.registered_at)}</div>
                  </div>

                  {p.face_images && p.face_images.length > 0 && (
                    <div className="flex gap-1.5 overflow-x-auto py-1">
                      {p.face_images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img}
                          alt="Face sample"
                          className="w-8 h-8 rounded-lg object-cover border border-slate-200 dark:border-white/10 flex-shrink-0 cursor-pointer hover:scale-105 transition-transform"
                          onClick={() => window.open(img, '_blank')}
                        />
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {filtered.length === 0 && (
              <div className="col-span-full text-center py-16 text-slate-500">
                <User className="w-12 h-12 mx-auto mb-2 opacity-30" />
                <p>No registered persons found.</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Edit Person Modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden">
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-800">
              <div>
                <h3 className="text-sm font-bold text-white">Edit Person</h3>
                <p className="text-[11px] text-slate-400 mt-0.5 font-mono">ID: {editing.person_id}</p>
              </div>
              <button
                onClick={() => setEditing(null)}
                className="p-1.5 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-4 max-h-[70vh] overflow-y-auto">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">First Name</label>
                  <input
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.first_name}
                    onChange={e => setForm(f => ({ ...f, first_name: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Last Name</label>
                  <input
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.last_name}
                    onChange={e => setForm(f => ({ ...f, last_name: e.target.value }))}
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Department</label>
                  <input
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.department}
                    onChange={e => setForm(f => ({ ...f, department: e.target.value }))}
                    placeholder="e.g. Engineering"
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Role</label>
                  <select
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.role}
                    onChange={e => setForm(f => ({ ...f, role: e.target.value }))}
                  >
                    {ROLE_OPTIONS.map(r => (
                      <option key={r} value={r}>{r}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Phone</label>
                  <input
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.phone}
                    onChange={e => setForm(f => ({ ...f, phone: e.target.value }))}
                  />
                </div>
                <div>
                  <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Email</label>
                  <input
                    type="email"
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500"
                    value={form.email}
                    onChange={e => setForm(f => ({ ...f, email: e.target.value }))}
                  />
                </div>
              </div>

              <div>
                <label className="block text-[11px] font-semibold text-slate-400 uppercase mb-1.5">Notes</label>
                <textarea
                  rows={3}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-100 focus:outline-none focus:border-blue-500 resize-none"
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 px-5 py-4 border-t border-slate-800 bg-slate-950/40">
              <button
                onClick={() => setEditing(null)}
                className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className={clsx(
                  'px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-1.5',
                  saving
                    ? 'bg-blue-600/50 text-blue-200 cursor-wait'
                    : 'bg-blue-600 hover:bg-blue-500 text-white'
                )}
              >
                <Save className="w-3.5 h-3.5" />
                {saving ? 'Saving…' : 'Save Changes'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
