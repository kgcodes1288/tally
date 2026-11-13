import { useState } from 'react'
import { ArrowUp, Lock, ServerCog, Sparkles, WifiOff } from 'lucide-react'
import type { Persona, Workspace } from '../lib/api'
import { MODELS, api } from '../lib/api'
import { Badge, Button, ErrorNote, cn } from './ui'
import { scopeText } from './Sidebar'

const SUGGESTIONS: Record<string, string[]> = {
  ws_federal: [
    'Investigate our unlinked File C records for FY2025: how much, which accounts, and the 10 largest. Cite the playbook.',
    'Reconcile File A with File B obligations for every Treasury account and explain any differences.',
    'Is our FY2025 obligation pace unusual compared with prior years? Build a dashboard.',
  ],
  ws_retail: [
    'Reconcile order payments against items plus freight. Classify the differences and give me a dashboard and a PDF for the CFO.',
    'Which product categories have the worst late-delivery rates, and how does lateness affect review scores?',
    'Run a data-quality check on orders and payments before I trust them for revenue reporting.',
  ],
  ws_city: [
    'Do heat complaints rise on cold days? Use the weather table and build a dashboard.',
    'Which complaint types have the slowest median response, and are any getting worse month over month?',
    'Run a data-quality check on 311 requests and tell me what to exclude before reporting response times.',
  ],
}

type Props = { ws: Workspace; persona: Persona; maxBudget: number; onCreated: (id: string) => void }

export function Composer({ ws, persona, maxBudget, onCreated }: Props) {
  const [prompt, setPrompt] = useState('')
  const [model, setModel] = useState<string>(MODELS[0].id)
  const [budget, setBudget] = useState(Math.min(0.5, maxBudget))
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function run() {
    if (prompt.trim().length < 3 || busy) return
    setBusy(true); setErr(null)
    try {
      const { id } = await api.create({ workspace: ws.id, persona: persona.id, prompt: prompt.trim(), model, budget_usd: budget })
      setPrompt(''); onCreated(id)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 pt-[9vh] pb-12">
      <div className="text-center">
        <Badge tone="brand" className="mb-3">{ws.name}</Badge>
        <h1 className="text-3xl font-bold tracking-tight">What should Tally work on?</h1>
        <p className="mx-auto mt-2 max-w-xl text-[15px] text-ink-2">{ws.description}</p>
      </div>

      <div className="mt-7 rounded-2xl border border-line bg-surface p-3 shadow-[0_2px_12px_rgba(20,25,35,.06)] focus-within:border-accent/60">
        <textarea
          value={prompt} onChange={e => setPrompt(e.target.value)} rows={4} autoFocus
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) run() }}
          placeholder="Ask a question or assign a task. For example: reconcile these two sources and give me a dashboard."
          className="w-full resize-none bg-transparent px-2 py-1.5 text-[15px] leading-relaxed outline-none placeholder:text-ink-3"
          aria-label="Task for Tally"
        />
        <div className="flex flex-wrap items-center gap-3 border-t border-line px-1 pt-2.5">
          <div className="flex rounded-lg bg-canvas p-0.5" role="radiogroup" aria-label="Model">
            {MODELS.map(m => (
              <button key={m.id} role="radio" aria-checked={model === m.id} title={m.hint} onClick={() => setModel(m.id)}
                className={cn('rounded-md px-3 py-1.5 text-[13px] font-semibold transition',
                  model === m.id ? 'bg-surface text-ink shadow-sm' : 'text-ink-3 hover:text-ink-2')}>
                {m.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-2 text-[13px] text-ink-2">
            Budget
            <input type="range" min={0.1} max={maxBudget} step={0.05} value={budget} onChange={e => setBudget(Number(e.target.value))}
              className="w-28 accent-[var(--color-accent)]" aria-label="Task budget in dollars" />
            <span className="w-11 font-semibold tabular-nums text-ink">${budget.toFixed(2)}</span>
          </label>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-[12px] text-ink-3 sm:inline">Ctrl + Enter</span>
            <Button onClick={run} disabled={busy || prompt.trim().length < 3}>
              {busy ? 'Starting…' : 'Run'}<ArrowUp className="size-4" />
            </Button>
          </div>
        </div>
      </div>
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}

      <div className="mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[12.5px] text-ink-3">
        <span className="flex items-center gap-1.5"><Lock className="size-3.5" />As <b className="font-semibold text-ink-2">{persona.title}</b> · {scopeText(persona, ws)}</span>
        <span className="flex items-center gap-1.5"><ServerCog className="size-3.5" />Own gVisor sandbox</span>
        <span className="flex items-center gap-1.5"><WifiOff className="size-3.5" />No internet, read-only data</span>
      </div>

      <div className="mt-9">
        <div className="mb-2 flex items-center gap-1.5 text-[12px] font-bold uppercase tracking-wider text-ink-3"><Sparkles className="size-3.5" />Try one of these</div>
        <div className="grid gap-2">
          {(SUGGESTIONS[ws.id] ?? []).map(s => (
            <button key={s} onClick={() => setPrompt(s)}
              className="rounded-xl border border-line bg-surface px-4 py-3 text-left text-[14px] text-ink-2 transition hover:border-accent/50 hover:text-ink">
              {s}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
