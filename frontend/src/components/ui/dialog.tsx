import * as React from 'react'
import * as D from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({ className, children, title, description, ...props }: React.ComponentProps<typeof D.Content> & { title: string; description?: string }) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-50 bg-black/50" />
      <D.Content
        className={cn(
          'fixed left-1/2 top-1/2 z-50 grid max-h-[90vh] w-[calc(100vw-2rem)] max-w-lg -translate-x-1/2 -translate-y-1/2 gap-4 overflow-y-auto rounded-lg border bg-background p-5 shadow-lg',
          className,
        )}
        {...props}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <D.Title className="text-base font-semibold">{title}</D.Title>
            {description ? <D.Description className="mt-1 text-sm text-muted-foreground">{description}</D.Description> : <D.Description className="sr-only">{title}</D.Description>}
          </div>
          <D.Close className="rounded-sm opacity-70 hover:opacity-100" aria-label="Close">
            <X className="size-4" />
          </D.Close>
        </div>
        {children}
      </D.Content>
    </D.Portal>
  )
}

/** Right-hand drawer on desktop, full screen on phone. */
export function Sheet({ open, onOpenChange, title, children }: { open: boolean; onOpenChange: (o: boolean) => void; title: string; children: React.ReactNode }) {
  return (
    <D.Root open={open} onOpenChange={onOpenChange}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
        <D.Content
          className="fixed inset-y-0 right-0 z-40 flex w-full flex-col border-l bg-background shadow-xl sm:max-w-2xl"
          aria-describedby={undefined}
        >
          <D.Title className="sr-only">{title}</D.Title>
          <D.Close className="absolute right-3 top-3 z-10 rounded-sm p-1 opacity-70 hover:bg-accent hover:opacity-100" aria-label="Close">
            <X className="size-5" />
          </D.Close>
          <div className="flex-1 overflow-y-auto">{children}</div>
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
