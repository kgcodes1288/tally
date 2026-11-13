import { useEffect, useRef, useState } from 'react'

export type Persona = {
  id: string
  workspace_id: string
  title: string
  description: string
  all_scopes: boolean
  scopes: string[]
}

export type Workspace = {
  id: string
  name: string
  description: string
  scope_label: string
  personas: Persona[]
}

export type TaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'stopped' | 'budget_exceeded'

export type TaskSummary = {
  id: string
  workspace_id: string
  persona: string
  model: string
  prompt: string
  status: TaskStatus
  spent_usd: number
  budget_usd: number
  created_at: string
  finished_at: string | null
}

export type OutputFile = { path: string; bytes: number }

export type TaskDetail = TaskSummary & {
  workspace_name: string
  persona_title: string
  result: string | null
  error: string | null
  started_at: string | null
  files: OutputFile[]
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type TaskEvent = { id: number; kind: string; data: Record<string, any> & { ts?: string } }

export type Usage = { today_usd: number; tasks_today: number; daily_cap_usd: number; running: number; max_concurrent: number }

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, { headers: { 'content-type': 'application/json' }, ...init })
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail ?? `${r.status} ${r.statusText}`)
  }
  return r.json()
}

export const api = {
  workspaces: () => req<Workspace[]>('/api/workspaces'),
  tasks: () => req<TaskSummary[]>('/api/tasks?limit=40'),
  task: (id: string) => req<TaskDetail>(`/api/tasks/${id}`),
  usage: () => req<Usage>('/api/usage'),
  create: (body: { workspace: string; persona: string; prompt: string; model: string; budget_usd: number }) =>
    req<{ id: string }>('/api/tasks', { method: 'POST', body: JSON.stringify(body) }),
  steer: (id: string, text: string) =>
    req<{ message_id: number }>(`/api/tasks/${id}/messages`, { method: 'POST', body: JSON.stringify({ body: text }) }),
  stop: (id: string) => req<{ stopping: boolean }>(`/api/tasks/${id}/stop`, { method: 'POST' }),
  fileUrl: (id: string, path: string) => `/api/tasks/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`,
}

const EVENT_KINDS = ['status', 'text', 'thinking', 'tool_call', 'tool_result', 'steer_queued', 'steer_delivered',
  'usage', 'artifact', 'result', 'error', 'system', 'log']

/** Live (or replayed) event stream for a task. The server replays history first, so a finished task renders the same way. */
export function useTaskEvents(taskId: string | null) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [ended, setEnded] = useState(false)
  const seen = useRef(new Set<number>())

  useEffect(() => {
    setEvents([]); setEnded(false); seen.current = new Set()
    if (!taskId) return
    const es = new EventSource(`/api/tasks/${taskId}/events`)
    const onEvent = (kind: string) => (e: MessageEvent) => {
      const id = Number(e.lastEventId)
      if (seen.current.has(id)) return            // EventSource may resend after a reconnect
      seen.current.add(id)
      setEvents(prev => [...prev, { id, kind, data: JSON.parse(e.data) }])
    }
    for (const k of EVENT_KINDS) es.addEventListener(k, onEvent(k) as EventListener)
    es.addEventListener('end', () => { setEnded(true); es.close() })
    return () => es.close()
  }, [taskId])

  return { events, ended }
}

export function usePolling<T>(fn: () => Promise<T>, ms: number, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null)
  useEffect(() => {
    let alive = true
    const tick = () => fn().then(d => alive && setData(d)).catch(() => {})
    tick()
    const t = setInterval(tick, ms)
    return () => { alive = false; clearInterval(t) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return data
}

export const money = (v: number | null | undefined, digits = 2) =>
  v == null ? '$0.00' : `$${Number(v).toFixed(v < 0.1 && v > 0 ? 3 : digits)}`

export function timeAgo(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export const MODELS = [
  { id: 'claude-sonnet-5-5', label: 'Sonnet 5.5', hint: 'Fast and economical' },
  { id: 'claude-opus-5-5', label: 'Opus 5.5', hint: 'Deepest reasoning' },
] as const
