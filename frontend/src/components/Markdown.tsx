import { lazy, Suspense } from 'react'
import { Textarea } from './ui/input'

const Editor = lazy(() => import('./MarkdownImpl').then((m) => ({ default: m.MdEditorImpl })))
const View = lazy(() => import('./MarkdownImpl').then((m) => ({ default: m.MdViewImpl })))

export function MdEditor(props: { value: string; onChange: (v: string) => void; height?: number }) {
  return (
    <Suspense fallback={<Textarea value={props.value} onChange={(e) => props.onChange(e.target.value)} rows={8} />}>
      <Editor {...props} />
    </Suspense>
  )
}

export function MdView({ source }: { source: string }) {
  return (
    <Suspense fallback={<p className="whitespace-pre-wrap text-sm">{source}</p>}>
      <View source={source} />
    </Suspense>
  )
}
