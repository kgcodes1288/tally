import { useEffect, useState } from 'react'
import { Download, ExternalLink, FileBarChart2, FileJson, FileSpreadsheet, FileText, ShieldAlert, X } from 'lucide-react'
import type { OutputFile } from '../lib/api'
import { api } from '../lib/api'
import { Button, Markdown, cn } from './ui'

const ext = (p: string) => p.split('.').pop()?.toLowerCase() ?? ''
const KIND: Record<string, { label: string; Icon: typeof FileText; tone: string }> = {
  html: { label: 'Dashboard', Icon: FileBarChart2, tone: 'bg-accent-soft text-accent' },
  pdf: { label: 'PDF report', Icon: FileText, tone: 'bg-bad/10 text-bad' },
  csv: { label: 'CSV data', Icon: FileSpreadsheet, tone: 'bg-good/10 text-good' },
  md: { label: 'Markdown', Icon: FileText, tone: 'bg-brand/10 text-brand' },
  json: { label: 'JSON', Icon: FileJson, tone: 'bg-black/[.05] text-ink-2' },
}
const size = (b: number) => (b > 1e6 ? `${(b / 1e6).toFixed(1)} MB` : b > 1e3 ? `${Math.round(b / 1e3)} KB` : `${b} B`)

/** Minimal CSV parser that handles quoted fields with commas and newlines. */
function parseCsv(text: string, limit = 200) {
  const rows: string[][] = []; let row: string[] = []; let f = ''; let q = false
  for (let i = 0; i < text.length && rows.length <= limit; i++) {
    const c = text[i]
    if (q) { if (c === '"' && text[i + 1] === '"') { f += '"'; i++ } else if (c === '"') q = false; else f += c }
    else if (c === '"') q = true
    else if (c === ',') { row.push(f); f = '' }
    else if (c === '\n') { row.push(f.replace(/\r$/, '')); rows.push(row); row = []; f = '' }
    else f += c
  }
  if (f || row.length) { row.push(f); rows.push(row) }
  return rows
}

function Preview({ url, file, onClose }: { url: string; file: OutputFile; onClose: () => void }) {
  const e = ext(file.path)
  const [text, setText] = useState<string | null>(null)
  useEffect(() => {
    if (['csv', 'md', 'json', 'txt'].includes(e)) fetch(url).then(r => r.text()).then(setText)
    const onKey = (ev: KeyboardEvent) => ev.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  }, [url, e, onClose])
  const rows = e === 'csv' && text ? parseCsv(text) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#0b1220]/60 p-4 backdrop-blur-sm" role="dialog" aria-modal aria-label={file.path} onClick={onClose}>
      <div className="flex h-[92vh] w-[min(1280px,96vw)] flex-col overflow-hidden rounded-2xl bg-surface shadow-2xl" onClick={ev => ev.stopPropagation()}>
        <div className="flex items-center gap-3 border-b border-line px-4 py-2.5">
          <div className="min-w-0 flex-1 truncate font-semibold">{file.path}</div>
          {e === 'html' && <span className="hidden items-center gap-1 text-[12px] text-ink-3 md:flex"><ShieldAlert className="size-3.5" />Agent-made page, shown in an isolated sandbox</span>}
          <a href={url} target="_blank" rel="noreferrer"><Button variant="ghost" size="sm"><ExternalLink className="size-4" />Open</Button></a>
          <a href={url} download><Button variant="outline" size="sm"><Download className="size-4" />Download</Button></a>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close preview"><X className="size-4" /></Button>
        </div>
        <div className="min-h-0 flex-1 overflow-auto bg-canvas">
          {/* Agent-written HTML is untrusted: no same-origin access, so it cannot read the app, its cookies or the API. */}
          {e === 'html' && <iframe src={url} sandbox="allow-scripts" className="h-full w-full bg-white" title={file.path} />}
          {e === 'pdf' && <iframe src={url} className="h-full w-full" title={file.path} />}
          {rows && (
            <table className="w-full border-collapse bg-surface text-[12.5px]">
              <thead className="sticky top-0 bg-canvas"><tr>{rows[0]?.map((h, i) => <th key={i} className="border-b border-line px-3 py-2 text-left font-semibold whitespace-nowrap text-ink-2">{h}</th>)}</tr></thead>
              <tbody>{rows.slice(1).map((r, i) => <tr key={i} className="odd:bg-black/[.015]">{r.map((c, j) => <td key={j} className="border-b border-line/60 px-3 py-1.5 whitespace-nowrap">{c}</td>)}</tr>)}</tbody>
            </table>
          )}
          {e === 'md' && text && <div className="mx-auto max-w-3xl bg-surface p-8"><Markdown>{text}</Markdown></div>}
          {(e === 'json' || e === 'txt') && text && <pre className="p-5 font-mono text-[12.5px] whitespace-pre-wrap">{text}</pre>}
          {rows && rows.length > 200 && <div className="p-3 text-[12px] text-ink-3">Showing the first 200 rows. Download for the full file.</div>}
        </div>
      </div>
    </div>
  )
}

export function Outputs({ taskId, files, urlFor }: { taskId: string; files: OutputFile[]; urlFor?: (path: string) => string }) {
  const link = urlFor ?? ((path: string) => api.fileUrl(taskId, path))
  const [open, setOpen] = useState<OutputFile | null>(null)
  const order = ['html', 'pdf', 'md', 'csv', 'json']
  const sorted = [...files].sort((a, b) => (order.indexOf(ext(a.path)) + 9) % 9 - (order.indexOf(ext(b.path)) + 9) % 9)
  return (
    <>
      <div className="space-y-1.5">
        {sorted.map(f => {
          const k = KIND[ext(f.path)] ?? { label: ext(f.path).toUpperCase(), Icon: FileText, tone: 'bg-black/[.05] text-ink-2' }
          return (
            <button key={f.path} onClick={() => setOpen(f)}
              className="flex w-full items-center gap-3 rounded-xl border border-line bg-surface px-3 py-2.5 text-left transition hover:border-accent/50">
              <span className={cn('grid size-9 shrink-0 place-items-center rounded-lg', k.tone)}><k.Icon className="size-4" /></span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[13.5px] font-semibold text-ink">{f.path}</span>
                <span className="text-[12px] text-ink-3">{k.label} · {size(f.bytes)}</span>
              </span>
            </button>
          )
        })}
      </div>
      {open && <Preview url={link(open.path)} file={open} onClose={() => setOpen(null)} />}
    </>
  )
}
