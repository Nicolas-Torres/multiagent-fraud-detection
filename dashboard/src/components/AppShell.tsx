import { NavLink, Outlet } from 'react-router-dom'

import { cn } from '@/lib/utils'

const LINKS = [
  { to: '/', label: 'Inicio', end: true },
  { to: '/queue', label: 'Cola (vista analista)', end: false },
  { to: '/policies', label: 'Políticas', end: false },
  { to: '/evaluation', label: 'Evaluación', end: false },
  { to: '/architecture', label: 'Cómo se construyó', end: false },
]

export function AppShell() {
  return (
    <div className="min-h-svh bg-background text-foreground">
      <header className="border-b">
        <div className="mx-auto flex max-w-6xl items-center gap-6 px-6 py-4">
          <span className="font-semibold">Detección de Fraude — Dashboard del analista</span>
          <nav className="flex gap-4 text-sm">
            {LINKS.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                end={link.end}
                className={({ isActive }) =>
                  cn(
                    'text-muted-foreground hover:text-foreground',
                    isActive && 'font-medium text-foreground',
                  )
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-6 py-6">
        <Outlet />
      </main>
    </div>
  )
}
