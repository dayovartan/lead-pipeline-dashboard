import { Check, Monitor, Moon, Palette, Sun } from 'lucide-react'
import { ACCENTS, type Mode, setTheme, useTheme } from '@/lib/theme'
import { cn } from '@/lib/utils'
import { Button } from './ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuTrigger } from './ui/dropdown-menu'

const MODES: { id: Mode; label: string; Icon: typeof Sun }[] = [
  { id: 'system', label: 'System', Icon: Monitor },
  { id: 'light', label: 'Light', Icon: Sun },
  { id: 'dark', label: 'Dark', Icon: Moon },
]

export function ThemeMenu() {
  const t = useTheme()
  const Current = t.mode === 'system' ? Monitor : t.dark ? Moon : Sun
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Theme" title="Theme">
          <Current className="size-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        {MODES.map(({ id, label, Icon }) => (
          <DropdownMenuItem key={id} onSelect={() => setTheme({ mode: id })}>
            <Icon className="size-4" /> {label}
            {t.mode === id ? <Check className="ml-auto size-4" /> : null}
          </DropdownMenuItem>
        ))}
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="flex items-center gap-1.5"><Palette className="size-3" /> Accent</DropdownMenuLabel>
        <div className="grid grid-cols-6 gap-1 px-2 pb-2 pt-1" role="radiogroup" aria-label="Accent colour">
          {ACCENTS.map((a) => (
            <button
              key={a.id}
              type="button"
              role="radio"
              aria-checked={t.accent === a.id}
              aria-label={a.label}
              title={a.label}
              onClick={() => setTheme({ accent: a.id })}
              className={cn('grid size-6 place-items-center rounded-full ring-offset-2 ring-offset-popover', t.accent === a.id && 'ring-2 ring-foreground')}
              style={{ background: a.swatch }}
            >
              {t.accent === a.id ? <Check className="size-3.5 text-white" /> : null}
            </button>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
