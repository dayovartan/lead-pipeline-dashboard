import * as React from 'react'
import * as T from '@radix-ui/react-tabs'
import { cn } from '@/lib/utils'

export const Tabs = T.Root

export function TabsList({ className, ...props }: React.ComponentProps<typeof T.List>) {
  return (
    <T.List
      className={cn('flex w-full items-center gap-1 overflow-x-auto border-b px-1 text-muted-foreground', className)}
      {...props}
    />
  )
}
export function TabsTrigger({ className, ...props }: React.ComponentProps<typeof T.Trigger>) {
  return (
    <T.Trigger
      className={cn(
        '-mb-px whitespace-nowrap border-b-2 border-transparent px-3 py-2 text-sm font-medium transition-colors hover:text-foreground data-[state=active]:border-primary data-[state=active]:text-foreground',
        className,
      )}
      {...props}
    />
  )
}
export function TabsContent({ className, ...props }: React.ComponentProps<typeof T.Content>) {
  return <T.Content className={cn('p-4 focus-visible:outline-none', className)} {...props} />
}
