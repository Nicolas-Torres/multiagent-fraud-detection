import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/transactions', label: 'Transactions', end: false },
  { to: '/queue', label: 'Cases / HITL', end: false },
  { to: '/policies', label: 'Policies', end: false },
  { to: '/architecture', label: 'Cómo se construyó', end: false },
]

// `/cases/:caseId` no está en `LINKS` -no es un link de nav, se llega
// clickeando una fila- y su título real es dinámico (incluye el UUID del
// caso); ese texto se queda donde ya está, dentro del contenido
// scrolleable de `CaseDetail`. Acá sólo hace falta un título genérico
// para el header fijo.
function tituloDe(pathname: string): string {
  if (pathname.startsWith('/cases/')) return 'Detalle del caso'
  const link = LINKS.find((l) => (l.end ? pathname === l.to : pathname.startsWith(l.to)))
  return link?.label ?? 'Detección de Fraude'
}

export function AppShell() {
  const [tema, alternarTema] = useTheme()
  const location = useLocation()

  return (
    <div className="flex h-svh overflow-hidden bg-background text-foreground">
      <aside className="flex w-56 shrink-0 flex-col border-r">
        <div className="border-b px-4 py-4">
          <span className="font-semibold">Detección de Fraude</span>
          <p className="text-xs text-muted-foreground">Dashboard del analista</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3 text-sm">
          {LINKS.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              end={link.end}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3 py-2 text-muted-foreground hover:bg-muted hover:text-foreground',
                  isActive && 'bg-secondary font-medium text-secondary-foreground',
                )
              }
            >
              {link.label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t p-3">
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={alternarTema}>
            {tema === 'dark' ? '☀️ Modo claro' : '🌙 Modo oscuro'}
          </Button>
        </div>
      </aside>
      {/* Segunda región de scroll, independiente del `<aside>`: el shell
          entero queda fijo a la altura del viewport (`h-svh overflow-hidden`
          arriba) y sólo esto -el `<main>` de abajo- scrollea. */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="shrink-0 border-b px-6 py-4">
          <h1 className="text-xl font-semibold">{tituloDe(location.pathname)}</h1>
        </header>
        <main className="flex-1 overflow-y-auto overflow-x-auto px-6 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
