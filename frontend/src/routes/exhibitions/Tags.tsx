import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Plus, Wand2, X } from 'lucide-react'
import { api } from '@/api/client'
import { PageHeader } from '@/components/bits'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input, Select } from '@/components/ui/input'
import { Empty, ErrorState, InlineError, Loading } from '@/components/ui/states'
import { useCanEdit, useDebounced } from '@/lib/hooks'
import { useTagOptions } from './MapPage'

export default function Tags() {
  const { slug = '' } = useParams()
  const canEdit = useCanEdit()
  const qc = useQueryClient()
  const cats = useQuery({ queryKey: ['categories', slug], queryFn: () => api.categories(slug) })
  const { tags, options, groups } = useTagOptions(slug)
  const [filter, setFilter] = useState('')
  const [unmappedOnly, setUnmappedOnly] = useState(false)
  const df = useDebounced(filter.toLowerCase(), 150)
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['categories', slug] })
    qc.invalidateQueries({ queryKey: ['tags', slug] })
  }
  const addRule = useMutation({ mutationFn: ({ category, tagId }: { category: string; tagId: number }) => api.createCategoryRule(slug, category, tagId), onSuccess: refresh })
  const delRule = useMutation({ mutationFn: (id: number) => api.deleteCategoryRule(slug, id), onSuccess: refresh })
  const tagFromCat = useMutation({
    mutationFn: async (category: string) => {
      const t = await api.createTag(slug, category)
      await api.createCategoryRule(slug, category, t.id)
    },
    onSuccess: refresh,
  })
  const tagById = useMemo(() => new Map(options.map((t) => [t.id, t])), [options])

  const rows = (cats.data ?? [])
    .filter((c) => !df || c.category.toLowerCase().includes(df))
    .filter((c) => !unmappedOnly || !(c.tag_ids?.length || c.rules?.length))
    .sort((a, b) => b.count - a.count)

  return (
    <>
      <PageHeader title="Tags" sub="Map the organiser's raw categories to this show's tags, then group the tags so they work as filters. Run suggestions on the Map page afterwards." />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <Card>
          <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
            <CardTitle>Raw categories {cats.data ? <span className="font-normal text-muted-foreground">({cats.data.length})</span> : null}</CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter…" className="h-8 w-48" aria-label="Filter categories" />
              <label className="flex items-center gap-1 text-xs text-muted-foreground">
                <input type="checkbox" checked={unmappedOnly} onChange={(e) => setUnmappedOnly(e.target.checked)} /> unmapped only
              </label>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {cats.isLoading ? <Loading /> : cats.isError ? <ErrorState error={cats.error} retry={cats.refetch} /> : rows.length === 0 ? <Empty title="No categories">Load the Excel first; categories come from its Categories column.</Empty> : null}
            <InlineError error={addRule.error ?? delRule.error ?? tagFromCat.error} />
            <ul className="divide-y">
              {rows.map((c) => {
                const mapped = c.rules?.length ? c.rules : (c.tag_ids ?? []).map((tag_id) => ({ id: 0, tag_id }))
                return (
                  <li key={c.category} className="flex flex-wrap items-center gap-2 px-4 py-2 text-sm">
                    <span className="min-w-0 flex-1 basis-56">
                      {c.category} <span className="tabular-nums text-xs text-muted-foreground">· {c.count}</span>
                    </span>
                    <span className="flex flex-wrap gap-1">
                      {mapped.map((r) => (
                        <Badge key={r.tag_id} variant="secondary" className="gap-1">
                          {tagById.get(r.tag_id)?.name ?? `#${r.tag_id}`}
                          {canEdit && r.id ? (
                            <button type="button" aria-label="Remove mapping" onClick={() => delRule.mutate(r.id)}>
                              <X className="size-3" />
                            </button>
                          ) : null}
                        </Badge>
                      ))}
                    </span>
                    {canEdit ? (
                      <span className="flex items-center gap-1">
                        <Select
                          aria-label={`Map ${c.category} to tag`}
                          value=""
                          className="h-8 max-w-[10rem] text-xs"
                          onChange={(e) => e.target.value && addRule.mutate({ category: c.category, tagId: Number(e.target.value) })}
                        >
                          <option value="">→ tag…</option>
                          {options.filter((t) => !mapped.some((m) => m.tag_id === t.id)).map((t) => (
                            <option key={t.id} value={t.id}>{t.group ? `${t.group} · ` : ''}{t.name}</option>
                          ))}
                        </Select>
                        {!mapped.length ? (
                          <Button size="icon" variant="ghost" className="size-8" title="Create a tag with this name and map it" aria-label={`Create tag ${c.category}`} onClick={() => tagFromCat.mutate(c.category)} disabled={tagFromCat.isPending}>
                            <Wand2 />
                          </Button>
                        ) : null}
                      </span>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          </CardContent>
        </Card>

        <div className="space-y-4">
          {tags.isLoading ? <Loading /> : tags.isError ? <ErrorState error={tags.error} retry={tags.refetch} /> : null}
          {canEdit ? <NewTagForms slug={slug} groups={groups} onDone={refresh} /> : null}
          {groups.map((g) => (
            <TagGroupCard key={g.id} slug={slug} title={g.name} tags={g.tags} groups={groups} canEdit={canEdit} onDone={refresh} />
          ))}
          {tags.data?.ungrouped.length ? <TagGroupCard slug={slug} title="Ungrouped" tags={tags.data.ungrouped} groups={groups} canEdit={canEdit} onDone={refresh} /> : null}
        </div>
      </div>
    </>
  )
}

type G = { id: number; name: string }

function NewTagForms({ slug, groups, onDone }: { slug: string; groups: G[]; onDone: () => void }) {
  const [group, setGroup] = useState('')
  const [tag, setTag] = useState('')
  const [tagGroup, setTagGroup] = useState('')
  const g = useMutation({ mutationFn: () => api.createTagGroup(slug, group.trim()), onSuccess: () => (setGroup(''), onDone()) })
  const t = useMutation({ mutationFn: () => api.createTag(slug, tag.trim(), tagGroup ? Number(tagGroup) : null), onSuccess: () => (setTag(''), onDone()) })
  return (
    <Card>
      <CardContent className="space-y-2 pt-4">
        <form className="flex gap-2" onSubmit={(e) => (e.preventDefault(), group.trim() && g.mutate())}>
          <Input value={group} onChange={(e) => setGroup(e.target.value)} placeholder="New group (e.g. RAM)" className="h-8" aria-label="New group name" />
          <Button type="submit" size="sm" variant="outline" disabled={!group.trim() || g.isPending}><Plus /> Group</Button>
        </form>
        <form className="flex gap-2" onSubmit={(e) => (e.preventDefault(), tag.trim() && t.mutate())}>
          <Input value={tag} onChange={(e) => setTag(e.target.value)} placeholder="New tag (e.g. DDR5)" className="h-8" aria-label="New tag name" />
          <Select value={tagGroup} onChange={(e) => setTagGroup(e.target.value)} className="h-8 max-w-[8rem] text-xs" aria-label="Group for new tag">
            <option value="">no group</option>
            {groups.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
          </Select>
          <Button type="submit" size="sm" variant="outline" disabled={!tag.trim() || t.isPending}><Plus /> Tag</Button>
        </form>
        <InlineError error={g.error ?? t.error} />
      </CardContent>
    </Card>
  )
}

function TagGroupCard({ slug, title, tags, groups, canEdit, onDone }: { slug: string; title: string; tags: { id: number; name: string; count: number }[]; groups: G[]; canEdit: boolean; onDone: () => void }) {
  const m = useMutation({ mutationFn: ({ id, b }: { id: number; b: { name?: string; group_id?: number | null } }) => api.patchTag(slug, id, b), onSuccess: onDone })
  const [editing, setEditing] = useState<number | null>(null)
  const [name, setName] = useState('')
  return (
    <Card>
      <CardHeader><CardTitle>{title} <span className="font-normal text-muted-foreground">({tags.length})</span></CardTitle></CardHeader>
      <CardContent>
        {tags.length === 0 ? <p className="text-sm text-muted-foreground">No tags.</p> : null}
        <ul className="space-y-1">
          {tags.map((t) => (
            <li key={t.id} className="flex items-center gap-2 text-sm">
              {editing === t.id ? (
                <form className="flex flex-1 gap-1" onSubmit={(e) => (e.preventDefault(), m.mutate({ id: t.id, b: { name: name.trim() } }), setEditing(null))}>
                  <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Escape' && setEditing(null)} className="h-7" />
                </form>
              ) : (
                <button type="button" disabled={!canEdit} className="flex-1 text-left enabled:hover:underline" onClick={() => (setEditing(t.id), setName(t.name))}>
                  {t.name}
                </button>
              )}
              <span className="tabular-nums text-xs text-muted-foreground">{t.count}</span>
              {canEdit ? (
                <Select aria-label={`Group of ${t.name}`} value="" className="h-7 w-24 text-xs" onChange={(e) => e.target.value && m.mutate({ id: t.id, b: { group_id: e.target.value === 'none' ? null : Number(e.target.value) } })}>
                  <option value="">move…</option>
                  <option value="none">no group</option>
                  {groups.map((g) => <option key={g.id} value={g.id}>{g.name}</option>)}
                </Select>
              ) : null}
            </li>
          ))}
        </ul>
        <InlineError error={m.error} />
      </CardContent>
    </Card>
  )
}
