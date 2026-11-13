import { useCallback, useEffect, useState } from 'react'
import { Gauge } from 'lucide-react'
import type { TaskSummary, Workspace } from './lib/api'
import { api, money, usePolling } from './lib/api'
import { Sidebar } from './components/Sidebar'
import { Composer } from './components/Composer'
import { TaskView } from './components/TaskView'

const route = () => window.location.hash.match(/^#\/task\/([0-9a-f-]{36})/)?.[1] ?? null

export default function App() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [wsId, setWsId] = useState(localStorage.getItem('tally.ws') ?? 'ws_federal')
  const [personaId, setPersonaId] = useState(localStorage.getItem('tally.persona') ?? '')
  const [taskId, setTaskId] = useState<string | null>(route())
  const [tick, setTick] = useState(0)
  const tasks = usePolling<TaskSummary[]>(api.tasks, 4000, [tick]) ?? []
  const usage = usePolling(api.usage, 10000, [tick])

  useEffect(() => { api.workspaces().then(setWorkspaces) }, [])
  useEffect(() => { const on = () => setTaskId(route()); window.addEventListener('hashchange', on); return () => window.removeEventListener('hashchange', on) }, [])

  const ws = workspaces.find(w => w.id === wsId) ?? workspaces[0]
  const persona = ws?.personas.find(p => p.id === personaId) ?? ws?.personas[0]
  useEffect(() => { if (ws) localStorage.setItem('tally.ws', ws.id); if (persona) localStorage.setItem('tally.persona', persona.id) }, [ws, persona])

  const open = (id: string | null) => { window.location.hash = id ? `/task/${id}` : '/' }
  // When a task is open, the sidebar shows the workspace and persona it ran as.
  const current = tasks.find(t => t.id === taskId)
  useEffect(() => { if (current) { setWsId(current.workspace_id); setPersonaId(current.persona) } }, [current?.id])  // eslint-disable-line react-hooks/exhaustive-deps
  const refresh = useCallback(() => setTick(t => t + 1), [])

  if (!ws || !persona) return <div className="grid h-full place-items-center text-ink-3">Loading Tally…</div>

  return (
    <div className="flex h-full">
      <Sidebar workspaces={workspaces} wsId={ws.id} personaId={persona.id} tasks={tasks} activeTask={taskId}
        onWorkspace={id => { setWsId(id); setPersonaId(''); open(null) }} onPersona={id => { setPersonaId(id); open(null) }}
        onNew={() => open(null)} onOpenTask={open} />
      <main className="relative min-w-0 flex-1 overflow-y-auto">
        {usage && !taskId && (
          <div className="absolute top-4 right-5 flex items-center gap-1.5 rounded-full border border-line bg-surface px-3 py-1.5 text-[12px] text-ink-2" title="Model spend today against the daily cap">
            <Gauge className="size-3.5 text-accent" />Today {money(usage.today_usd)} of {money(usage.daily_cap_usd)}
          </div>
        )}
        {taskId
          ? <TaskView key={taskId} taskId={taskId} onChanged={refresh} />
          : <Composer key={ws.id + persona.id} ws={ws} persona={persona} onCreated={id => { refresh(); open(id) }} />}
      </main>
    </div>
  )
}
