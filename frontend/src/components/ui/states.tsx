import * as React from 'react'
import { AlertTriangle, Inbox, Loader2, CloudOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { errorText } from '@/api/client'
import { Button } from './button'

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn('size-4 animate-spin', className)} aria-hidden />
}

export function Loading({ label = 'Loading…', className }: { label?: string; className?: string }) {
  return (
    <div role="status" className={cn('flex items-center justify-center gap-2 p-8 text-sm text-muted-foreground', className)}>
      <Spinner /> {label}
    </div>
  )
}

export function Empty({ title, children, className, icon }: { title: string; children?: React.ReactNode; className?: string; icon?: React.ReactNode }) {
  return (
    <div className={cn('flex flex-col items-center justify-center gap-2 p-8 text-center', className)}>
      <div className="text-muted-foreground">{icon ?? <Inbox className="size-6" />}</div>
      <p className="text-sm font-medium">{title}</p>
      {children ? <div className="max-w-md text-sm text-muted-foreground">{children}</div> : null}
    </div>
  )
}

export function ErrorState({ error, retry, className }: { error: unknown; retry?: () => void; className?: string }) {
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center gap-2 p-8 text-center', className)}>
      <AlertTriangle className="size-6 text-destructive" />
      <p className="text-sm font-medium">Something went wrong</p>
      <p className="max-w-md text-sm text-muted-foreground">{errorText(error)}</p>
      {retry ? (
        <Button size="sm" variant="outline" onClick={retry}>
          Try again
        </Button>
      ) : null}
    </div>
  )
}

export function Unavailable({ reason, what }: { reason?: string; what: string }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed p-3 text-sm text-muted-foreground">
      <CloudOff className="mt-0.5 size-4 shrink-0" />
      <div>
        <span className="font-medium text-foreground/80">{what} not available right now.</span>
        {reason ? <span className="block text-xs">{reason}</span> : null}
      </div>
    </div>
  )
}

export function InlineError({ error }: { error: unknown }) {
  if (!error) return null
  return <p className="text-sm text-destructive">{errorText(error)}</p>
}
