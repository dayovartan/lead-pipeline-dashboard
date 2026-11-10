import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { CompanyWindow } from '@/components/company/CompanyWindow'
import { Button } from '@/components/ui/button'

/** Full-page company window (phone, or a shared link). */
export default function CompanyPage() {
  const { id } = useParams()
  const [params, setParams] = useSearchParams()
  const show = params.get('show') ?? undefined
  const tab = params.get('tab') ?? undefined
  const back = `/leads/companies${show ? `?show=${encodeURIComponent(show)}` : ''}`
  return (
    <div className="-mx-4 -my-4 sm:mx-auto sm:my-0 sm:max-w-3xl">
      <Button asChild variant="ghost" size="sm" className="m-2">
        <Link to={back}>
          <ArrowLeft /> Companies
        </Link>
      </Button>
      <div className="border-y bg-background sm:rounded-lg sm:border">
        <CompanyWindow
          id={Number(id)}
          mode="leads"
          show={show}
          tab={tab}
          onTab={(t) => {
            const p = new URLSearchParams(params)
            p.set('tab', t)
            setParams(p, { replace: true })
          }}
        />
      </div>
    </div>
  )
}
