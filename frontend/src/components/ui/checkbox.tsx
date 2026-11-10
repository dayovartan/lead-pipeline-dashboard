import * as React from 'react'
import * as C from '@radix-ui/react-checkbox'
import { Check, Minus } from 'lucide-react'
import { cn } from '@/lib/utils'

export const Checkbox = React.forwardRef<React.ElementRef<typeof C.Root>, React.ComponentPropsWithoutRef<typeof C.Root>>(
  ({ className, ...props }, ref) => (
    <C.Root
      ref={ref}
      className={cn(
        'peer size-4 shrink-0 rounded-sm border border-primary shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50 data-[state=checked]:bg-primary data-[state=checked]:text-primary-foreground data-[state=indeterminate]:bg-primary data-[state=indeterminate]:text-primary-foreground',
        className,
      )}
      {...props}
    >
      <C.Indicator className="flex items-center justify-center text-current">
        {props.checked === 'indeterminate' ? <Minus className="size-3" /> : <Check className="size-[80%]" />}
      </C.Indicator>
    </C.Root>
  ),
)
Checkbox.displayName = 'Checkbox'
