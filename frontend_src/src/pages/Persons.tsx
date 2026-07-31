import { useEffect, useState } from 'react'
import { Search, Trash2, User, RefreshCw } from 'lucide-react'

import { TopBar } from '../components/TopBar'
import { getPersons, deletePerson } from '../lib/api'
import type { Person } from '../lib/api'

export function Persons() {
  const [persons, setPersons] = useState<Person[]>([])
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(true)

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

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete ${name} (${id})?`)) return
    try {
      await deletePerson(id)
      setPersons(prev => prev.filter(p => p.person_id !== id))
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
              <div key={p.person_id} className="glass rounded-2xl p-4 border border-white/5 hover:border-primary-500/20 transition-all flex flex-col justify-between">
                <div>
                  <div className="flex items-start justify-between gap-2 mb-3">
                    <div className="flex items-center gap-3">
                      {p.face_images && p.face_images.length > 0 ? (
                        <img src={p.face_images[0]} alt={p.name} className="w-12 h-12 rounded-xl object-cover border border-white/10" />
                      ) : (
                        <div className="w-12 h-12 rounded-xl bg-primary-500/15 text-primary-400 flex items-center justify-center font-bold">
                          <User className="w-6 h-6" />
                        </div>
                      )}
                      <div>
                        <h3 className="font-semibold text-white text-sm line-clamp-1">{p.name}</h3>
                        <p className="text-xs text-primary-400 font-mono">ID: {p.person_id}</p>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDelete(p.person_id, p.name)}
                      className="text-slate-500 hover:text-red-400 p-1.5 rounded-lg hover:bg-red-500/10 transition-colors"
                      title="Delete Person"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  <div className="text-xs text-slate-400 space-y-1 mb-3">
                    <div className="flex items-center justify-between">
                      <span>Sample Embeddings</span>
                      <span className="badge-blue text-[10px]">{p.embedding_count}</span>
                    </div>
                    <div className="text-[10px] text-slate-500">Registered: {p.registered_at}</div>
                  </div>

                  {p.face_images && p.face_images.length > 0 && (
                    <div className="flex gap-1.5 overflow-x-auto py-1">
                      {p.face_images.map((img, idx) => (
                        <img
                          key={idx}
                          src={img}
                          alt="Face sample"
                          className="w-8 h-8 rounded-lg object-cover border border-white/10 flex-shrink-0 cursor-pointer hover:scale-105 transition-transform"
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
    </div>
  )
}
