import { useConventions } from '@/lib/hooks'
import { useCurrentShow } from '@/lib/show'
import { Select } from './ui/input'
import { cn } from '@/lib/utils'

export function ShowPicker({ className }: { className?: string }) {
  const { data, isLoading } = useConventions()
  const { slug, setShow } = useCurrentShow()
  const known = data?.some((c) => c.slug === slug)
  return (
    <Select
      aria-label="Current show"
      value={slug}
      onChange={(e) => setShow(e.target.value)}
      className={cn('max-w-[12rem]', className)}
      disabled={isLoading}
    >
      <option value="">All shows</option>
      {slug && !known && !isLoading ? <option value={slug}>{slug}</option> : null}
      {data?.map((c) => (
        <option key={c.slug} value={c.slug}>
          {c.name}
        </option>
      ))}
    </Select>
  )
}
