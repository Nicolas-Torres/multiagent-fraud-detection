import { NavLink, Outlet } from 'react-router-dom'

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

export function AppShell() {
  const [tema, alternarTema] = useTheme()

  return (
    <div className="flex min-h-svh bg-background text-foreground">
      <aside className="flex w-56 shrink-0 flex-col border-r">
        <div className="border-b px-4 py-4">
          <span className="font-semibold">Detección de Fraude</span>
          <p className="text-xs text-muted-foreground">Dashboard del analista</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3 text-sm">
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
      <main className="min-w-0 flex-1 overflow-x-auto px-6 py-6">
        <div className="mx-auto max-w-6xl">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
