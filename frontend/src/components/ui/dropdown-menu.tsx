import * as React from 'react'
import * as M from '@radix-ui/react-dropdown-menu'
import { cn } from '@/lib/utils'

export const DropdownMenu = M.Root
export const DropdownMenuTrigger = M.Trigger

export function DropdownMenuContent({ className, sideOffset = 4, ...props }: React.ComponentProps<typeof M.Content>) {
  return (
    <M.Portal>
      <M.Content
        sideOffset={sideOffset}
        className={cn('z-50 min-w-[10rem] overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-md', className)}
        {...props}
      />
    </M.Portal>
  )
}
export function DropdownMenuItem({ className, ...props }: React.ComponentProps<typeof M.Item>) {
  return (
    <M.Item
      className={cn(
        'relative flex cursor-default select-none items-center gap-2 rounded-sm px-2 py-1.5 text-sm outline-none focus:bg-accent data-[disabled]:pointer-events-none data-[disabled]:opacity-50',
        className,
      )}
      {...props}
    />
  )
}
export function DropdownMenuLabel({ className, ...props }: React.ComponentProps<typeof M.Label>) {
  return <M.Label className={cn('px-2 py-1 text-xs font-semibold text-muted-foreground', className)} {...props} />
}
export function DropdownMenuSeparator({ className, ...props }: React.ComponentProps<typeof M.Separator>) {
  return <M.Separator className={cn('-mx-1 my-1 h-px bg-border', className)} {...props} />
}
