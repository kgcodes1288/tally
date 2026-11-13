import { Building2, Landmark, Plus, ShieldCheck, ShoppingBag } from 'lucide-react'
import type { Persona, TaskSummary, Workspace } from '../lib/api'
import { money, timeAgo } from '../lib/api'
import { Button, STATUS, cn } from './ui'

const WS_ICON: Record<string, typeof Landmark> = { ws_federal: Landmark, ws_retail: ShoppingBag, ws_city: Building2 }

export function scopeText(p: Persona, ws?: Workspace) {
  if (p.all_scopes) return `All ${ws?.scope_label ?? 'scope'} values`
  return `${ws?.scope_label ? ws.scope_label[0].toUpperCase() + ws.scope_label.slice(1) : 'Scope'}: ${p.scopes.join(', ')}`
}

type Props = {
  workspaces: Workspace[]
  wsId: string
  personaId: string
  tasks: TaskSummary[]
  activeTask: string | null
  onWorkspace: (id: string) => void
  onPersona: (id: string) => void
  onNew: () => void
  onOpenTask: (id: string) => void
}

export function Sidebar({ workspaces, wsId, personaId, tasks, activeTask, onWorkspace, onPersona, onNew, onOpenTask }: Props) {
  const ws = workspaces.find(w => w.id === wsId)
  return (
    <aside className="flex h-full w-[300px] shrink-0 flex-col border-r border-line bg-surface">
      <div className="flex items-center gap-2.5 px-5 pt-5 pb-4">
        <img src="/tally.svg" alt="" className="size-8" />
        <div>
          <div className="text-[17px] font-bold leading-none tracking-tight">Tally</div>
          <div className="mt-1 text-[11.5px] text-ink-3">Agentic data work, safely</div>
        </div>
      </div>

      <div className="px-3">
        <div className="px-2 pb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink-3">Workspace</div>
        <div className="space-y-0.5">
          {workspaces.map(w => {
            const Icon = WS_ICON[w.id] ?? Landmark
            const on = w.id === wsId
            return (
              <button key={w.id} onClick={() => onWorkspace(w.id)}
                className={cn('flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-sm transition',
                  on ? 'bg-brand text-white' : 'text-ink hover:bg-black/[.04]')}>
                <Icon className={cn('size-4 shrink-0', on ? 'text-white' : 'text-ink-2')} aria-hidden />
                <span className="font-semibold">{w.name}</span>
              </button>
            )
          })}
        </div>
      </div>

      {ws && (
        <div className="mt-4 px-3">
          <div className="flex items-center justify-between px-2 pb-1.5">
            <span className="text-[11px] font-bold uppercase tracking-wider text-ink-3">Acting as</span>
            <span className="flex items-center gap-1 text-[11px] text-ink-3"><ShieldCheck className="size-3" />enforced by the database</span>
          </div>
          <div className="max-h-[34vh] space-y-1 overflow-y-auto pr-1">
            {ws.personas.map(p => {
              const on = p.id === personaId
              return (
                <button key={p.id} onClick={() => onPersona(p.id)} aria-pressed={on}
                  className={cn('w-full rounded-lg border px-3 py-2 text-left transition',
                    on ? 'border-accent bg-accent-soft' : 'border-transparent hover:bg-black/[.03]')}>
                  <div className={cn('text-[13.5px] font-semibold', on ? 'text-accent' : 'text-ink')}>{p.title}</div>
                  <div className="mt-0.5 text-[11.5px] text-ink-3">{scopeText(p, ws)}</div>
                </button>
              )
            })}
          </div>
        </div>
      )}

      <div className="mt-4 px-5"><Button className="w-full" onClick={onNew}><Plus className="size-4" />New task</Button></div>

      <div className="mt-4 flex min-h-0 flex-1 flex-col border-t border-line">
        <div className="px-5 pt-3 pb-1.5 text-[11px] font-bold uppercase tracking-wider text-ink-3">Recent tasks</div>
        <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-3 pb-4">
          {tasks.length === 0 && <div className="px-2 py-3 text-sm text-ink-3">No tasks yet.</div>}
          {tasks.map(t => {
            const s = STATUS[t.status]
            return (
              <button key={t.id} onClick={() => onOpenTask(t.id)}
                className={cn('w-full rounded-lg px-2.5 py-2 text-left transition', t.id === activeTask ? 'bg-black/[.06]' : 'hover:bg-black/[.03]')}>
                <div className="flex items-start gap-2">
                  <span className={cn('mt-1.5 size-2 shrink-0 rounded-full', s?.dot)} aria-label={s?.label} />
                  <span className="line-clamp-2 text-[13px] leading-snug text-ink">{t.prompt}</span>
                </div>
                <div className="mt-1 pl-4 text-[11.5px] text-ink-3">{timeAgo(t.created_at)} · {money(t.spent_usd)}</div>
              </button>
            )
          })}
        </div>
      </div>
    </aside>
  )
}
