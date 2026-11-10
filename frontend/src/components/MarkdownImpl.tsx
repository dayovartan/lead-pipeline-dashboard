import MDEditor from '@uiw/react-md-editor/nohighlight'
import { useMediaQuery } from '@/lib/hooks'

export function MdEditorImpl({ value, onChange, height = 220 }: { value: string; onChange: (v: string) => void; height?: number }) {
  const dark = useMediaQuery('(prefers-color-scheme: dark)')
  return (
    <div data-color-mode={dark ? 'dark' : 'light'}>
      <MDEditor
        value={value}
        onChange={(v) => onChange(v ?? '')}
        height={height}
        preview="edit"
        visibleDragbar={false}
        textareaProps={{ placeholder: 'What was discussed? Markdown welcome.' }}
      />
    </div>
  )
}

export function MdViewImpl({ source }: { source: string }) {
  const dark = useMediaQuery('(prefers-color-scheme: dark)')
  return (
    <div data-color-mode={dark ? 'dark' : 'light'}>
      <MDEditor.Markdown source={source} skipHtml />
    </div>
  )
}
