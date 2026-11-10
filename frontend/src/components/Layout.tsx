import { Suspense } from 'react'
import { Outlet, useLocation, useSearchParams } from 'react-router-dom'
import { useCurrentShow, useShowSync } from '@/lib/show'
import { TopBar } from './TopBar'
import { CompanyWindow } from './company/CompanyWindow'
import { Sheet } from './ui/dialog'
import { Loading } from './ui/states'

export function Layout() {
  useShowSync()
  return (
    <div className="flex min-h-full flex-col">
      <TopBar />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-4">
        <Suspense fallback={<Loading />}>
          <Outlet />
        </Suspense>
      </main>
      <CompanyDrawer />
    </div>
  )
}

/** The company window as a drawer, driven by ?company=<id>&tab=<tab>. */
function CompanyDrawer() {
  const [params, setParams] = useSearchParams()
  const { pathname } = useLocation()
  const { slug } = useCurrentShow()
  const id = Number(params.get('company'))
  const tab = params.get('tab') ?? undefined
  const mode = pathname.startsWith('/exhibitions') ? 'exhibitions' : 'leads'
  const close = () => {
    const p = new URLSearchParams(params)
    p.delete('company')
    p.delete('tab')
    setParams(p)
  }
  const setTab = (t: string) => {
    const p = new URLSearchParams(params)
    p.set('tab', t)
    setParams(p, { replace: true })
  }
  if (!id) return null
  return (
    <Sheet open onOpenChange={(o) => !o && close()} title="Company">
      <CompanyWindow key={id} id={id} mode={mode} show={slug || undefined} tab={tab} onTab={setTab} />
    </Sheet>
  )
}
