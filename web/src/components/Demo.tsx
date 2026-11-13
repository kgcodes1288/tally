import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowLeft, Clock, FastForward, Lock, Pause, Play, RotateCcw, ServerCog, ShieldCheck, WifiOff } from 'lucide-react'
import type { OutputFile, TaskEvent } from '../lib/api'
import { MODELS, money } from '../lib/api'
import { Badge, Button, Card } from './ui'
import { Timeline, buildSteps } from './Timeline'
import { Outputs } from './Outputs'

/* Public replay mode at /demo: recordings of real Tally runs. No login, no model calls, nothing can be started. */

type Replay = { id: string; title: string; blurb: string | null; workspace_name: string; persona_title: string; model: string; spent_usd: number; seconds: number }
type ReplayDetail = Replay & { prompt: string; files: OutputFile[]; events: TaskEvent[] }

const fileUrl = (id: string, path: string) => `/api/public/replays/${id}/files/${path.split('/').map(encodeURIComponent).join('/')}`
const dur = (s: number) => (s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`)
const modelName = (m: string) => MODELS.find(x => x.id === m)?.label ?? m

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-5 py-3">
          <a href="/demo" className="flex items-center gap-2.5"><img src="/tally.svg" alt="" className="size-7" /><span className="font-bold">Tally</span></a>
          <Badge tone="accent">Replays of real runs</Badge>
          <div className="ml-auto flex items-center gap-1 text-[13px]">
            <a className="rounded-lg px-2.5 py-1.5 text-ink-2 hover:bg-black/5" href="https://karthickg.dev" target="_blank" rel="noreferrer">karthickg.dev</a>
            <a className="rounded-lg px-2.5 py-1.5 text-ink-2 hover:bg-black/5" href="https://www.linkedin.com/in/karthickgovin" target="_blank" rel="noreferrer">LinkedIn</a>
          </div>
        </div>
      </header>
      {children}
    </div>
  )
}

function Gallery() {
  const [list, setList] = useState<Replay[] | null>(null)
  useEffect(() => { fetch('/api/public/replays').then(r => r.json()).then(setList).catch(() => setList([])) }, [])
  return (
    <Shell>
      <div className="mx-auto max-w-6xl px-5 py-10">
        <h1 className="text-3xl font-bold tracking-tight">Watch Tally work</h1>
        <p className="mt-2 max-w-3xl text-[15.5px] text-ink-2">
          Tally is a self-hosted platform for agentic data work. You ask in plain English; an AI agent works in its own isolated sandbox,
          using only the data your role may see, and returns answers, dashboards and reports. These are recordings of real runs on public data,
          replayed step by step: every query, knowledge-base search, mid-task note and output. Live runs are invite-only.
        </p>
        <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 text-[13px] text-ink-3">
          <span className="flex items-center gap-1.5"><ServerCog className="size-3.5" />A gVisor sandbox per task</span>
          <span className="flex items-center gap-1.5"><Lock className="size-3.5" />Row-level security by role</span>
          <span className="flex items-center gap-1.5"><WifiOff className="size-3.5" />No internet inside the sandbox</span>
          <span className="flex items-center gap-1.5"><ShieldCheck className="size-3.5" />API key held by a proxy</span>
        </div>
        <div className="mt-8 grid gap-4 md:grid-cols-2">
          {list?.map(r => (
            <a key={r.id} href={`/demo/${r.id}`} className="group">
              <Card className="h-full p-5 transition group-hover:border-accent/50">
                <div className="flex flex-wrap gap-1.5"><Badge tone="brand">{r.workspace_name}</Badge><Badge>{r.persona_title}</Badge></div>
                <h2 className="mt-3 text-[17px] font-semibold leading-snug">{r.title}</h2>
                {r.blurb && <p className="mt-1.5 text-[14px] text-ink-2">{r.blurb}</p>}
                <div className="mt-4 flex items-center gap-3 text-[12.5px] text-ink-3">
                  <span className="flex items-center gap-1"><Clock className="size-3.5" />{dur(r.seconds)}</span>
                  <span>{money(r.spent_usd)}</span><span>{modelName(r.model)}</span>
                  <span className="ml-auto flex items-center gap-1 font-semibold text-accent"><Play className="size-3.5 fill-current" />Watch replay</span>
                </div>
              </Card>
            </a>
          ))}
          {list?.length === 0 && <p className="text-ink-3">No replays published yet.</p>}
        </div>
      </div>
    </Shell>
  )
}

function Player({ id }: { id: string }) {
  const [d, setD] = useState<ReplayDetail | null>(null)
  const [shown, setShown] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [speed, setSpeed] = useState(2)
  const timer = useRef<number | undefined>(undefined)
  useEffect(() => { fetch(`/api/public/replays/${id}`).then(r => (r.ok ? r.json() : null)).then(setD) }, [id])

  // Pace playback on the real gaps between events, compressed so long waits do not drag.
  useEffect(() => {
    if (!d || !playing || shown >= d.events.length) return
    const prev = d.events[shown - 1]?.data.ts, next = d.events[shown]?.data.ts
    const gap = prev && next ? (new Date(next).getTime() - new Date(prev).getTime()) : 300
    const wait = Math.min(Math.max(gap, 150), 1800) / speed
    timer.current = window.setTimeout(() => setShown(n => n + 1), wait)
    return () => window.clearTimeout(timer.current)
  }, [d, playing, shown, speed])

  const visible = useMemo(() => (d ? d.events.slice(0, shown) : []), [d, shown])
  const steps = useMemo(() => buildSteps(visible), [visible])
  const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => { if (playing) bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [steps.length, playing])

  if (!d) return <Shell><div className="p-10 text-ink-3">Loading replay…</div></Shell>
  const done = shown >= d.events.length
  const spent = [...visible].reverse().find(e => e.kind === 'usage')?.data.task_spent_usd ?? 0
  const sandbox = d.events.find(e => e.kind === 'status' && e.data.status === 'starting')?.data

  return (
    <Shell>
      <div className="mx-auto max-w-6xl px-5 py-5">
        <a href="/demo" className="inline-flex items-center gap-1 text-[13px] text-ink-3 hover:text-ink"><ArrowLeft className="size-3.5" />All replays</a>
        <div className="mt-2 flex flex-wrap items-center gap-1.5"><Badge tone="brand">{d.workspace_name}</Badge><Badge>{d.persona_title}</Badge><Badge>{modelName(d.model)}</Badge></div>
        <h1 className="mt-2 text-2xl font-bold tracking-tight">{d.title}</h1>
        <p className="mt-1 text-[14.5px] text-ink-2"><span className="font-semibold text-ink">Asked:</span> {d.prompt}</p>

        <div className="sticky top-0 z-10 mt-4 flex flex-wrap items-center gap-2 rounded-xl border border-line bg-surface/95 px-3 py-2 backdrop-blur">
          <Button size="sm" variant="dark" onClick={() => (done ? (setShown(0), setPlaying(true)) : setPlaying(!playing))}>
            {done ? <><RotateCcw className="size-4" />Replay</> : playing ? <><Pause className="size-4" />Pause</> : <><Play className="size-4" />Play</>}
          </Button>
          <div className="flex rounded-lg bg-canvas p-0.5" role="radiogroup" aria-label="Playback speed">
            {[1, 2, 4].map(s => <button key={s} role="radio" aria-checked={speed === s} onClick={() => setSpeed(s)}
              className={`rounded-md px-2.5 py-1 text-[12.5px] font-semibold ${speed === s ? 'bg-surface shadow-sm' : 'text-ink-3'}`}>{s}×</button>)}
          </div>
          <Button size="sm" variant="ghost" onClick={() => { setShown(d.events.length); setPlaying(false); setTimeout(() => bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }), 150) }}><FastForward className="size-4" />Skip to result</Button>
          <div className="ml-auto flex items-center gap-3 text-[12.5px] text-ink-3">
            <span>Step {Math.min(shown, d.events.length)} of {d.events.length}</span>
            <span className="font-semibold text-ink">{money(Number(spent))}</span>
          </div>
          <div className="h-1 w-full overflow-hidden rounded-full bg-black/[.06]"><div className="h-full bg-accent transition-all" style={{ width: `${(shown / d.events.length) * 100}%` }} /></div>
        </div>

        <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div><Timeline steps={steps} live={!done && playing} /><div ref={bottom} /></div>
          <aside className="space-y-4 lg:sticky lg:top-24 lg:self-start">
            {done && d.files.length > 0 && (
              <div><div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-ink-3">Outputs</div>
                <Outputs taskId={d.id} files={d.files} urlFor={p => fileUrl(d.id, p)} /></div>
            )}
            <Card className="p-4">
              <div className="mb-2 text-[11px] font-bold uppercase tracking-wider text-ink-3">How this task ran</div>
              <ul className="space-y-2 text-[12.5px] text-ink-2">
                <li className="flex gap-2"><ServerCog className="mt-0.5 size-3.5 shrink-0 text-brand" />Its own gVisor sandbox, destroyed afterwards</li>
                <li className="flex gap-2"><Lock className="mt-0.5 size-3.5 shrink-0 text-brand" />Database login scoped to {sandbox?.scope ?? 'the persona'}, expiring within the hour</li>
                <li className="flex gap-2"><WifiOff className="mt-0.5 size-3.5 shrink-0 text-brand" />No internet; read-only data access</li>
                <li className="flex gap-2"><ShieldCheck className="mt-0.5 size-3.5 shrink-0 text-brand" />Ran in {dur(d.seconds)} for {money(d.spent_usd)}</li>
              </ul>
            </Card>
          </aside>
        </div>
      </div>
    </Shell>
  )
}

export function Demo() {
  const id = window.location.pathname.match(/^\/demo\/([0-9a-f-]{36})/)?.[1]
  return id ? <Player id={id} /> : <Gallery />
}
