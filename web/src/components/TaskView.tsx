import { useEffect, useMemo, useRef, useState } from 'react'
import { Clock, Cpu, KeyRound, Lock, Send, ServerCog, Square, WifiOff } from 'lucide-react'
import type { TaskDetail } from '../lib/api'
import { MODELS, api, money, useTaskEvents } from '../lib/api'
import { Badge, Button, Card, ErrorNote, StatusPill, cn } from './ui'
import { Timeline, buildSteps } from './Timeline'
import { Outputs } from './Outputs'

function useElapsed(start: string | null, end: string | null) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => { if (end) return; const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t) }, [end])
  if (!start) return null
  const s = Math.max(0, Math.round(((end ? new Date(end).getTime() : now) - new Date(start).getTime()) / 1000))
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

function CostMeter({ spent, budget }: { spent: number; budget: number }) {
  const pct = Math.min(100, (spent / budget) * 100)
  return (
    <div className="w-44" title="Model cost so far, against this task's budget">
      <div className="flex justify-between text-[12px]"><span className="font-semibold tabular-nums text-ink">{money(spent)}</span><span className="text-ink-3">of {money(budget)}</span></div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-black/[.07]" role="progressbar" aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full rounded-full transition-all', pct > 85 ? 'bg-warn' : 'bg-accent')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export function TaskView({ taskId, onChanged }: { taskId: string; onChanged: () => void }) {
  const [task, setTask] = useState<TaskDetail | null>(null)
  const [note, setNote] = useState('')
  const [err, setErr] = useState<string | null>(null)
  const { events, ended } = useTaskEvents(taskId)
  const bottom = useRef<HTMLDivElement>(null)

  // Refresh the task record when it starts, finishes, or produces a file.
  const marks = events.filter(e => e.kind === 'status' || e.kind === 'artifact' || e.kind === 'result').length
  useEffect(() => { api.task(taskId).then(setTask).catch(e => setErr(e.message)) }, [taskId, marks, ended])
  useEffect(() => { if (ended) onChanged() }, [ended, onChanged])

  const steps = useMemo(() => buildSteps(events), [events])
  const live = !!task && ['queued', 'running'].includes(task.status) && !ended
  useEffect(() => { if (live) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [steps.length, live])

  const lastUsage = [...events].reverse().find(e => e.kind === 'usage')
  const spent = lastUsage ? Number(lastUsage.data.task_spent_usd) : Number(task?.spent_usd ?? 0)
  const sandbox = events.find(e => e.kind === 'status' && e.data.status === 'starting')?.data
  const result = events.find(e => e.kind === 'result')?.data
  const elapsed = useElapsed(task?.started_at ?? null, task?.finished_at ?? null)

  async function send() {
    if (!note.trim()) return
    try { await api.steer(taskId, note.trim()); setNote('') } catch (e) { setErr((e as Error).message) }
  }
  async function stop() {
    try { await api.stop(taskId) } catch (e) { setErr((e as Error).message) }
  }

  if (!task) return <div className="p-10 text-ink-3">{err ?? 'Loading…'}</div>
  const model = MODELS.find(m => m.id === task.model)?.label ?? task.model

  return (
    <div className="flex min-h-full flex-col lg:h-full lg:min-h-0">
      <header className="border-b border-line bg-surface px-4 py-3 lg:px-7 lg:py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <StatusPill status={task.status} />
              <Badge tone="brand">{task.workspace_name}</Badge>
              <Badge>{task.persona_title}</Badge>
              <Badge>{model}</Badge>
              {elapsed && <span className="flex items-center gap-1 text-[12px] text-ink-3"><Clock className="size-3.5" />{elapsed}</span>}
            </div>
            <h1 className="mt-2 line-clamp-2 text-[17px] font-semibold leading-snug text-ink">{task.prompt}</h1>
          </div>
          <CostMeter spent={spent} budget={Number(task.budget_usd)} />
        </div>
      </header>

      <div className="grid flex-1 grid-cols-1 lg:min-h-0 lg:grid-cols-[minmax(0,1fr)_360px] lg:overflow-hidden">
        <div className="flex flex-col lg:min-h-0">
          <div className="px-4 py-4 lg:min-h-0 lg:flex-1 lg:overflow-y-auto lg:px-7 lg:py-5">
            <Timeline steps={steps} live={live} />
            {task.status === 'budget_exceeded' && <div className="mt-3"><ErrorNote>The task used its whole budget and was stopped. Results so far are kept.</ErrorNote></div>}
            <div ref={bottom} />
          </div>
          {live && (
            <div className="sticky bottom-0 border-t border-line bg-surface px-4 py-3 lg:static lg:px-7">
              <div className="flex items-end gap-2">
                <textarea value={note} onChange={e => setNote(e.target.value)} rows={1}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() } }}
                  placeholder="Add a note while Tally works. It reads it at its next step, without stopping."
                  className="max-h-28 min-h-10 flex-1 resize-none rounded-xl border border-line bg-canvas px-3.5 py-2.5 text-[14px] outline-none focus:border-accent/60"
                  aria-label="Steering note" />
                <Button onClick={send} disabled={!note.trim()} aria-label="Send note"><Send className="size-4" /></Button>
                <Button variant="danger" onClick={stop}><Square className="size-3.5 fill-current" />Stop</Button>
              </div>
              {err && <div className="mt-2"><ErrorNote>{err}</ErrorNote></div>}
            </div>
          )}
        </div>

        <aside className="space-y-4 border-t lg:min-h-0 lg:overflow-y-auto border-line bg-canvas/60 px-4 py-5 lg:border-t-0 lg:border-l lg:px-5">
          {task.files_expired && <Card className="p-4 text-[13px] text-ink-3">Output files are kept for 30 days and have been removed. The activity timeline is kept.</Card>}
          {task.files.length > 0 && (
            <div>
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-ink-3">Outputs</div>
              <Outputs taskId={task.id} files={task.files} />
            </div>
          )}
          <Card className="p-4">
            <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-ink-3">How this task ran</div>
            <ul className="space-y-2 text-[12.5px] text-ink-2">
              <li className="flex gap-2"><ServerCog className="mt-0.5 size-3.5 shrink-0 text-brand" />Its own {sandbox?.sandbox ?? 'gVisor'} sandbox, destroyed afterwards</li>
              <li className="flex gap-2"><Lock className="mt-0.5 size-3.5 shrink-0 text-brand" />Database login scoped to {sandbox?.scope ?? 'this persona'}, expires within the hour</li>
              <li className="flex gap-2"><WifiOff className="mt-0.5 size-3.5 shrink-0 text-brand" />No internet; read-only data access</li>
              <li className="flex gap-2"><KeyRound className="mt-0.5 size-3.5 shrink-0 text-brand" />API key held by a proxy, never inside the sandbox</li>
              {result?.turns != null && <li className="flex gap-2"><Cpu className="mt-0.5 size-3.5 shrink-0 text-brand" />{result.turns} model turns · {money(spent)} total</li>}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  )
}
