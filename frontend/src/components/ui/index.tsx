import { cva, type VariantProps } from 'class-variance-authority'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TdHTMLAttributes, TextareaHTMLAttributes, ThHTMLAttributes } from 'react'
import { cn } from '@/utils/format'

// ---- Button (shadcn/ui style: cva variants) ---------------------------------------------------
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-navy-500 focus-visible:ring-offset-1 disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
  {
    variants: {
      variant: {
        primary: 'bg-navy-700 text-white shadow-sm hover:bg-navy-800',
        secondary: 'bg-white text-slate-700 border border-slate-200 shadow-sm hover:bg-slate-50',
        ghost: 'text-slate-600 hover:bg-slate-100',
        success: 'bg-ok-600 text-white shadow-sm hover:bg-ok-700',
        danger: 'bg-bad-600 text-white shadow-sm hover:bg-bad-700',
        warn: 'bg-warn-100 text-warn-700 border border-warn-100 hover:bg-amber-200',
      },
      size: { sm: 'h-8 px-3', md: 'h-9 px-4', lg: 'h-11 px-6 text-base', icon: 'h-8 w-8' },
    },
    defaultVariants: { variant: 'primary', size: 'md' },
  },
)

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {
  loading?: boolean
}
export function Button({ className, variant, size, loading, children, disabled, ...props }: ButtonProps) {
  return (
    <button className={cn(buttonVariants({ variant, size }), className)} disabled={disabled || loading} {...props}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  )
}

// ---- Card ---------------------------------------------------------------------------------------
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-xl border border-slate-200 bg-white shadow-sm', className)} {...props} />
}
export function CardHeader({ title, subtitle, action, className }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cn('flex items-start justify-between gap-3 border-b border-slate-100 px-5 py-4', className)}>
      <div className="min-w-0">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}
export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-5', className)} {...props} />
}

// ---- Badge ----------------------------------------------------------------------------------------
const badgeVariants = cva('inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap', {
  variants: {
    tone: {
      green: 'bg-ok-50 text-ok-700 ring-1 ring-inset ring-ok-100',
      amber: 'bg-warn-50 text-warn-700 ring-1 ring-inset ring-warn-100',
      red: 'bg-bad-50 text-bad-700 ring-1 ring-inset ring-bad-100',
      indigo: 'bg-navy-50 text-navy-700 ring-1 ring-inset ring-navy-100',
      slate: 'bg-slate-100 text-slate-600 ring-1 ring-inset ring-slate-200',
    },
  },
  defaultVariants: { tone: 'slate' },
})
export function Badge({ tone, className, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}

// ---- form controls ----------------------------------------------------------------------------------
const field = 'w-full rounded-lg border border-slate-200 bg-white px-3 text-sm text-slate-900 placeholder:text-slate-400 shadow-sm focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-200 disabled:bg-slate-50'
export function Input({ className, ...props }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(field, 'h-9', className)} {...props} />
}
export function Textarea({ className, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(field, 'py-2', className)} {...props} />
}
export function Select({ className, ...props }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={cn(field, 'h-9 pr-8', className)} {...props} />
}
export function Label({ children, hint }: { children: ReactNode; hint?: string }) {
  return (
    <label className="mb-1 block text-xs font-medium text-slate-600">
      {children}
      {hint && <span className="ml-1 font-normal text-slate-400">{hint}</span>}
    </label>
  )
}

// ---- feedback ---------------------------------------------------------------------------------------
export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('h-4 w-4 animate-spin text-navy-600', className)} />
}
export function PageLoading({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 py-20 text-sm text-slate-500" role="status">
      <Spinner /> {label}
    </div>
  )
}
export function EmptyState({ icon, title, hint, action }: { icon?: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      {icon && <div className="mb-3 rounded-full bg-slate-100 p-3 text-slate-400">{icon}</div>}
      <p className="text-sm font-medium text-slate-800">{title}</p>
      {hint && <p className="mt-1 max-w-sm text-xs text-slate-500">{hint}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}
export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div className="rounded-lg border border-bad-100 bg-bad-50 p-4 text-sm text-bad-700" role="alert">
      <p className="font-medium">We couldn’t load this.</p>
      <p className="mt-1 text-xs">{msg}</p>
      {onRetry && <Button variant="secondary" size="sm" className="mt-3" onClick={onRetry}>Try again</Button>}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

// ---- table ---------------------------------------------------------------------------------------------
export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn('overflow-x-auto', className)}>
      <table className="w-full text-left text-sm">{children}</table>
    </div>
  )
}
export const Th = ({ className, ...p }: ThHTMLAttributes<HTMLTableCellElement>) => (
  <th className={cn('whitespace-nowrap border-b border-slate-100 bg-slate-50/70 px-4 py-2.5 text-xs font-medium uppercase tracking-wide text-slate-500', className)} {...p} />
)
export const Td = ({ className, ...p }: TdHTMLAttributes<HTMLTableCellElement>) => (
  <td className={cn('border-b border-slate-100 px-4 py-3 align-middle text-slate-700', className)} {...p} />
)

export function Kv({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-1.5 text-sm">
      <dt className="shrink-0 text-slate-500">{k}</dt>
      <dd className={cn('min-w-0 text-right font-medium text-slate-900 break-words', mono && 'font-mono text-xs')}>{v ?? '—'}</dd>
    </div>
  )
}
