import * as React from 'react'
import { cn } from '@/lib/utils'

export function Table({ className, ...props }: React.HTMLAttributes<HTMLTableElement>) {
  return (
    <div className="relative w-full overflow-x-auto rounded-md border">
      <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
    </div>
  )
}
export const THead = ({ className, ...p }: React.HTMLAttributes<HTMLTableSectionElement>) => <thead className={cn('bg-muted/50 [&_tr]:border-b', className)} {...p} />
export const TBody = ({ className, ...p }: React.HTMLAttributes<HTMLTableSectionElement>) => <tbody className={cn('[&_tr:last-child]:border-0', className)} {...p} />
export function TR({ className, ...props }: React.HTMLAttributes<HTMLTableRowElement>) {
  return <tr className={cn('border-b transition-colors data-[state=selected]:bg-primary/5', className)} {...props} />
}
export function TH({ className, ...props }: React.ThHTMLAttributes<HTMLTableCellElement>) {
  return <th className={cn('h-9 whitespace-nowrap px-3 text-left align-middle text-xs font-medium text-muted-foreground', className)} {...props} />
}
export function TD({ className, ...props }: React.TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn('px-3 py-2 align-middle', className)} {...props} />
}
