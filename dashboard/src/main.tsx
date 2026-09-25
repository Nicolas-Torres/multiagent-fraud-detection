import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router-dom'

import { CasoNoEncontrado } from '@/api/cases'
import { AppShell } from '@/components/AppShell'
import { Architecture } from '@/routes/Architecture'
import { CaseDetail } from '@/routes/CaseDetail'
import { Dashboard } from '@/routes/Dashboard'
import { Policies } from '@/routes/Policies'
import { Queue } from '@/routes/Queue'
import { Transactions } from '@/routes/Transactions'

import './index.css'

// Un caso que no existe no va a aparecer reintentando: el resto de los
// errores conserva los 3 reintentos por defecto.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (intentos, error) => !(error instanceof CasoNoEncontrado) && intentos < 3,
    },
  },
})

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'transactions', element: <Transactions /> },
      { path: 'queue', element: <Queue /> },
      { path: 'cases/:caseId', element: <CaseDetail /> },
      { path: 'policies', element: <Policies /> },
      { path: 'architecture', element: <Architecture /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
