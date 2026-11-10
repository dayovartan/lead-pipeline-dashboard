import { lazy, Suspense } from 'react'
import { createBrowserRouter, Link, Navigate, useParams, useRouteError } from 'react-router-dom'
import { Layout } from './components/Layout'
import { Button } from './components/ui/button'
import { ErrorState, Loading } from './components/ui/states'
import { storedShow } from './lib/show'

const Board = lazy(() => import('./routes/leads/Board'))
const Companies = lazy(() => import('./routes/leads/Companies'))
const CompanyPage = lazy(() => import('./routes/leads/CompanyPage'))
const ContactPage = lazy(() => import('./routes/leads/ContactPage'))
const ShowList = lazy(() => import('./routes/exhibitions/ShowList'))
const Intake = lazy(() => import('./routes/exhibitions/Intake'))
const MapPage = lazy(() => import('./routes/exhibitions/MapPage'))
const Tags = lazy(() => import('./routes/exhibitions/Tags'))
const Coverage = lazy(() => import('./routes/exhibitions/Coverage'))
const Dispatch = lazy(() => import('./routes/exhibitions/Dispatch'))
const Floor = lazy(() => import('./routes/exhibitions/Floor'))

function RouteError() {
  const e = useRouteError()
  return <ErrorState error={e} retry={() => location.reload()} className="min-h-[50vh]" />
}

function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <p className="text-lg font-semibold">Page not found</p>
      <Button asChild variant="outline">
        <Link to="/leads/board">Go to the board</Link>
      </Button>
    </div>
  )
}

function ShowIndex() {
  const { slug } = useParams()
  return <Navigate to={`/exhibitions/${encodeURIComponent(slug!)}/map`} replace />
}

function Home() {
  const s = storedShow()
  return <Navigate to={`/leads/board${s ? `?show=${encodeURIComponent(s)}` : ''}`} replace />
}

export const router = createBrowserRouter([
  {
    path: '/',
    element: <Layout />,
    errorElement: <RouteError />,
    children: [
      { index: true, element: <Home /> },
      { path: 'leads', element: <Navigate to="/leads/board" replace /> },
      { path: 'leads/board', element: <Board /> },
      { path: 'leads/companies', element: <Companies /> },
      { path: 'leads/companies/:id', element: <CompanyPage /> },
      { path: 'leads/contacts/:id', element: <ContactPage /> },
      { path: 'exhibitions', element: <ShowList /> },
      { path: 'exhibitions/:slug', element: <ShowIndex /> },
      { path: 'exhibitions/:slug/intake', element: <Intake /> },
      { path: 'exhibitions/:slug/map', element: <MapPage /> },
      { path: 'exhibitions/:slug/tags', element: <Tags /> },
      { path: 'exhibitions/:slug/coverage', element: <Coverage /> },
      { path: 'exhibitions/:slug/dispatch', element: <Dispatch /> },
      { path: '*', element: <NotFound /> },
    ],
  },
  // phone floor list: its own minimal chrome
  {
    path: '/exhibitions/:slug/floor/:person',
    errorElement: <RouteError />,
    element: (
      <Suspense fallback={<Loading className="min-h-screen" />}>
        <Floor />
      </Suspense>
    ),
  },
])
