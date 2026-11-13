import { useState } from 'react'
import {
  BookOpen, CheckCheck, ChevronRight, Columns3, Database, Download, FileText, FolderSearch, Loader2, MessageSquareText,
  ServerCog, Sparkles, Table2, Terminal, UserRound,
} from 'lucide-react'
import type { TaskEvent } from '../lib/api'
import { Badge, Markdown, cn } from './ui'

type Step =
  | { type: 'tool'; id: string; name: string; input: Record<string, unknown>; result?: { text: string; is_error: boolean }; at: number }
  | { type: 'text'; text: string; at: number; final?: boolean }
  | { type: 'steer'; mid: number; body: string; delivered?: string; at: number }
  | { type: 'note'; text: string; tone?: 'muted' | 'error'; at: number }
  | { type: 'skills'; skills: string[]; at: number }

/** Fold the raw event stream into display steps: pair each tool call with its result, steering notes with delivery. */
export function buildSteps(events: TaskEvent[]): Step[] {
  const steps: Step[] = []
  const tools = new Map<string, Extract<Step, { type: 'tool' }>>()
  const steers = new Map<number, Extract<Step, { type: 'steer' }>>()
  for (const e of events) {
    const d = e.data
    switch (e.kind) {
      case 'tool_call': {
        const s: Step = { type: 'tool', id: d.id, name: d.name, input: d.input ?? {}, at: e.id }
        tools.set(d.id, s); steps.push(s); break
      }
      case 'tool_result': { const s = tools.get(d.id); if (s) s.result = { text: d.text ?? '', is_error: !!d.is_error }; break }
      case 'text': if (d.text?.trim()) steps.push({ type: 'text', text: d.text, at: e.id }); break
      case 'steer_queued': { const s: Step = { type: 'steer', mid: d.message_id, body: d.body, at: e.id }; steers.set(d.message_id, s); steps.push(s); break }
      case 'steer_delivered': { const s = steers.get(d.message_id); if (s) s.delivered = d.after_tool ?? 'next step'; break }
      case 'system': if (d.subtype === 'init' && d.skills?.length) steps.push({ type: 'skills', skills: d.skills, at: e.id }); break
      case 'status':
        if (d.status === 'starting') steps.push({ type: 'note', text: `Sandbox started (${d.sandbox}) as ${d.persona} · ${d.scope}`, at: e.id })
        if (d.status === 'stopping') steps.push({ type: 'note', text: 'Stop requested. Finishing the current step…', at: e.id })
        break
      case 'error': steps.push({ type: 'note', text: d.message, tone: 'error', at: e.id }); break
      case 'result': {
        const last = [...steps].reverse().find(s => s.type === 'text') as Extract<Step, { type: 'text' }> | undefined
        if (last && d.text && last.text.trim() === String(d.text).trim()) last.final = true
        else if (d.text) steps.push({ type: 'text', text: d.text, final: true, at: e.id })
        break
      }
    }
  }
  return steps
}

const TOOL_META: Record<string, { label: string; Icon: typeof Database }> = {
  whoami: { label: 'Checked who it is acting for', Icon: UserRound },
  list_tables: { label: 'Listed available tables', Icon: Table2 },
  describe_table: { label: 'Inspected a table', Icon: Columns3 },
  run_sql: { label: 'Ran a query', Icon: Database },
  export_query: { label: 'Exported data', Icon: Download },
  search_knowledge: { label: 'Searched the knowledge base', Icon: BookOpen },
  Skill: { label: 'Used a skill', Icon: Sparkles },
  Bash: { label: 'Ran a command', Icon: Terminal },
  Read: { label: 'Read a file', Icon: FileText },
  Write: { label: 'Wrote a file', Icon: FileText },
  Edit: { label: 'Edited a file', Icon: FileText },
  Glob: { label: 'Looked for files', Icon: FolderSearch },
  Grep: { label: 'Searched files', Icon: FolderSearch },
}

/** "a | b\n--- | ---\n1 | 2" (the data tools' format) -> rows */
function parsePipeTable(text: string) {
  const lines = text.split('\n').filter(l => l.includes(' | ') || /^---( \| ---)*$/.test(l))
  if (lines.length < 2 || !/^---/.test(lines[1])) return null
  const head = lines[0].split(' | ')
  const rows = lines.slice(2).map(l => l.split(' | '))
  return { head, rows }
}

function MiniTable({ head, rows }: { head: string[]; rows: string[][] }) {
  return (
    <div className="mt-2 max-h-64 overflow-auto rounded-lg border border-line">
      <table className="w-full border-collapse text-[12px]">
        <thead className="sticky top-0 bg-canvas"><tr>{head.map((h, i) => <th key={i} className="border-b border-line px-2 py-1.5 text-left font-semibold whitespace-nowrap text-ink-2">{h}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 50).map((r, i) => (
          <tr key={i} className="odd:bg-black/[.015]">{r.map((c, j) => <td key={j} className={cn('border-b border-line/60 px-2 py-1 whitespace-nowrap', /^-?[\d,.]+$/.test(c) && 'text-right tabular-nums')}>{c}</td>)}</tr>
        ))}</tbody>
      </table>
      {rows.length > 50 && <div className="px-2 py-1 text-[11px] text-ink-3">{rows.length - 50} more rows</div>}
    </div>
  )
}

function Citations({ text }: { text: string }) {
  const hits = [...text.matchAll(/^\[(\d+)\] (.+?) \(authority: (\w+)\)$/gm)]
  if (!hits.length) return <pre className="mt-2 max-h-48 overflow-auto rounded-lg bg-canvas p-2.5 text-[12px] whitespace-pre-wrap">{text}</pre>
  const tone = (a: string) => (a === 'official' ? 'brand' : a === 'internal' ? 'accent' : a === 'uploaded' ? 'gold' : 'neutral') as 'brand'
  return (
    <ol className="mt-2 space-y-1.5">
      {hits.map(h => (
        <li key={h[1]} className="flex items-start gap-2 text-[12.5px]">
          <span className="mt-0.5 font-mono text-ink-3">[{h[1]}]</span>
          <span className="flex-1 text-ink">{h[2]}</span>
          <Badge tone={tone(h[3])}>{h[3]}</Badge>
        </li>
      ))}
    </ol>
  )
}

function ToolCard({ s }: { s: Extract<Step, { type: 'tool' }> }) {
  const [open, setOpen] = useState(s.name === 'run_sql' || s.name === 'search_knowledge')
  const meta = TOOL_META[s.name] ?? { label: s.name, Icon: ServerCog }
  const running = !s.result
  const inp = s.input as Record<string, string>
  const summary = s.name === 'Skill' ? inp.skill
    : s.name === 'search_knowledge' ? `“${inp.query}”`
    : s.name === 'describe_table' ? inp.table
    : s.name === 'export_query' ? inp.filename
    : ['Read', 'Write', 'Edit'].includes(s.name) ? String(inp.file_path ?? '').replace('/workspace/', '')
    : s.name === 'Bash' ? String(inp.description ?? inp.command ?? '').split('\n')[0].slice(0, 90)
    : ''
  const code = s.name === 'run_sql' || s.name === 'export_query' ? inp.sql : s.name === 'Bash' ? inp.command : null
  const table = s.result && !s.result.is_error ? parsePipeTable(s.result.text) : null

  return (
    <div className={cn('rounded-xl border bg-surface', s.result?.is_error ? 'border-bad/40' : 'border-line')}>
      <button onClick={() => setOpen(!open)} className="flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left" aria-expanded={open}>
        <span className={cn('grid size-7 shrink-0 place-items-center rounded-lg', s.name === 'Skill' ? 'bg-gold/10 text-gold' : 'bg-brand/[.07] text-brand')}>
          {running ? <Loader2 className="size-3.5 animate-spin" /> : <meta.Icon className="size-3.5" />}
        </span>
        <span className="text-[13.5px] font-semibold text-ink">{meta.label}</span>
        {summary && <span className="min-w-0 truncate text-[13px] text-ink-2">{summary}</span>}
        {s.result?.is_error && <Badge className="bg-bad/10 text-bad">error</Badge>}
        <ChevronRight className={cn('ml-auto size-4 shrink-0 text-ink-3 transition', open && 'rotate-90')} />
      </button>
      {open && (
        <div className="border-t border-line px-3.5 pt-2 pb-3">
          {code && <pre className="max-h-56 overflow-auto rounded-lg bg-[#0f1720] p-2.5 font-mono text-[12px] leading-relaxed whitespace-pre-wrap text-[#dbe4ee]">{code}</pre>}
          {s.result && (s.name === 'search_knowledge' ? <Citations text={s.result.text} />
            : table ? <MiniTable {...table} />
            : s.result.text && <pre className={cn('mt-2 max-h-56 overflow-auto rounded-lg p-2.5 text-[12px] whitespace-pre-wrap', s.result.is_error ? 'bg-bad/5 text-bad' : 'bg-canvas text-ink-2')}>{s.result.text}</pre>)}
          {running && <div className="mt-2 text-[12.5px] text-ink-3">Working…</div>}
        </div>
      )}
    </div>
  )
}

export function Timeline({ steps, live }: { steps: Step[]; live: boolean }) {
  return (
    <ol className="relative space-y-2.5" aria-live="polite">
      {steps.map((s, i) => (
        <li key={`${s.type}-${s.at}-${i}`}>
          {s.type === 'tool' && <ToolCard s={s} />}
          {s.type === 'text' && s.final && (
            <div className="rounded-2xl border border-accent/40 bg-surface p-5 shadow-[0_2px_12px_rgba(15,123,108,.08)]">
              <div className="mb-1 flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wider text-accent"><CheckCheck className="size-3.5" />Answer</div>
              <Markdown>{s.text}</Markdown>
            </div>
          )}
          {s.type === 'text' && !s.final && (
            <div className="flex gap-2.5 px-1 py-1">
              <MessageSquareText className="mt-1 size-4 shrink-0 text-accent" aria-hidden />
              <div className="min-w-0 flex-1"><Markdown>{s.text}</Markdown></div>
            </div>
          )}
          {s.type === 'steer' && (
            <div className="flex justify-end">
              <div className="max-w-[80%] rounded-2xl rounded-br-md bg-brand px-3.5 py-2 text-[14px] text-white">
                <div>{s.body}</div>
                <div className="mt-1 text-[11.5px] text-white/70">{s.delivered ? `Delivered to Tally after: ${s.delivered}` : 'Queued, delivered at Tally’s next step…'}</div>
              </div>
            </div>
          )}
          {s.type === 'skills' && (
            <div className="flex flex-wrap items-center gap-1.5 px-1 text-[12.5px] text-ink-3">
              <Sparkles className="size-3.5 text-gold" /> Skills available:
              {s.skills.map(k => <Badge key={k} tone="gold">{k}</Badge>)}
            </div>
          )}
          {s.type === 'note' && <div className={cn('px-1 text-[12.5px]', s.tone === 'error' ? 'text-bad' : 'text-ink-3')}>{s.text}</div>}
        </li>
      ))}
      {live && <li className="flex items-center gap-2 px-1 py-1 text-[13px] text-ink-3"><span className="size-2 rounded-full bg-accent pulse-dot" />Tally is working…</li>}
    </ol>
  )
}
