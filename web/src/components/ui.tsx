import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { cva, type VariantProps } from 'class-variance-authority'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { CheckCircle2, CircleDashed, Loader2, OctagonX, PauseCircle, Wallet, XCircle } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import type { TaskStatus } from '../lib/api'

export const cn = (...c: ClassValue[]) => twMerge(clsx(c))

const button = cva(
  'inline-flex items-center justify-center gap-2 rounded-lg text-sm font-semibold transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-accent text-white hover:brightness-110 shadow-sm',
        dark: 'bg-brand text-white hover:bg-brand-2',
        outline: 'border border-line bg-surface text-ink hover:border-ink-3',
        ghost: 'text-ink-2 hover:bg-black/5',
        danger: 'border border-bad/40 bg-surface text-bad hover:bg-bad/5',
      },
      size: { sm: 'h-8 px-3', md: 'h-10 px-4', lg: 'h-11 px-5 text-[15px]' },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export function Button({ className, variant, size, ...p }: ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>) {
  return <button className={cn(button({ variant, size }), className)} {...p} />
}

export function Badge({ children, className, tone = 'neutral' }: { children: ReactNode; className?: string; tone?: 'neutral' | 'accent' | 'brand' | 'gold' }) {
  const tones = {
    neutral: 'bg-black/[.05] text-ink-2',
    accent: 'bg-accent-soft text-accent',
    brand: 'bg-brand/10 text-brand',
    gold: 'bg-gold/10 text-gold',
  }
  return <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11.5px] font-semibold', tones[tone], className)}>{children}</span>
}

export const STATUS: Record<TaskStatus, { label: string; cls: string; dot: string; Icon: typeof CheckCircle2 }> = {
  queued: { label: 'Queued', cls: 'bg-black/[.05] text-ink-2', dot: 'bg-ink-3', Icon: CircleDashed },
  running: { label: 'Running', cls: 'bg-accent-soft text-accent', dot: 'bg-accent pulse-dot', Icon: Loader2 },
  succeeded: { label: 'Done', cls: 'bg-good/10 text-good', dot: 'bg-good', Icon: CheckCircle2 },
  failed: { label: 'Failed', cls: 'bg-bad/10 text-bad', dot: 'bg-bad', Icon: XCircle },
  stopped: { label: 'Stopped', cls: 'bg-warn/10 text-warn', dot: 'bg-warn', Icon: PauseCircle },
  budget_exceeded: { label: 'Budget used up', cls: 'bg-warn/10 text-warn', dot: 'bg-warn', Icon: Wallet },
}

export function StatusPill({ status }: { status: TaskStatus }) {
  const s = STATUS[status] ?? STATUS.failed
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold', s.cls)}>
      <s.Icon className={cn('size-3.5', status === 'running' && 'animate-spin')} aria-hidden />
      {s.label}
    </span>
  )
}

export function Markdown({ children }: { children: string }) {
  return <div className="md"><ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown></div>
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('rounded-2xl border border-line bg-surface shadow-[0_1px_2px_rgba(20,25,35,.04)]', className)}>{children}</div>
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div className="flex items-start gap-2 rounded-lg border border-bad/30 bg-bad/5 px-3 py-2 text-sm text-bad"><OctagonX className="mt-0.5 size-4 shrink-0" />{children}</div>
}
