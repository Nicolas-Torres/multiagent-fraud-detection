import { useState } from 'react'
import { MenuIcon } from 'lucide-react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { useTheme } from '@/hooks/useTheme'
import { cn } from '@/lib/utils'

const LINKS = [
  { to: '/', label: 'Dashboard', end: true },
  { to: '/transactions', label: 'Transactions', end: false },
  { to: '/queue', label: 'Human-in-the-loop (HITL)', end: false },
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
  const [navAbierta, setNavAbierta] = useState(false)

  const enlaces = (
    <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-3 text-sm">
      {LINKS.map((link) => (
        <NavLink
          key={link.to}
          to={link.to}
          end={link.end}
          onClick={() => setNavAbierta(false)}
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
  )

  const toggleTema = (
    <Button variant="ghost" size="sm" className="w-full justify-start" onClick={alternarTema}>
      {tema === 'dark' ? '☀️ Modo claro' : '🌙 Modo oscuro'}
    </Button>
  )

  return (
    <Sheet open={navAbierta} onOpenChange={setNavAbierta}>
      <div className="flex h-svh overflow-hidden bg-background text-foreground">
        <aside className="hidden w-56 shrink-0 flex-col border-r md:flex">
          <div className="border-b px-4 py-4">
            <span className="font-semibold">Detección de Fraude</span>
            <p className="text-xs text-muted-foreground">Dashboard del analista</p>
          </div>
          {enlaces}
          <div className="border-t p-3">{toggleTema}</div>
        </aside>

        {/* Mismo contenido que el `<aside>`, como drawer: sólo se monta bajo
            `md` (el trigger de abajo tiene `md:hidden`), nunca compiten. */}
        <SheetContent side="left" className="flex w-56 max-w-none flex-col gap-0 p-0 sm:max-w-none">
          <SheetHeader className="border-b px-4 py-4">
            <SheetTitle>Detección de Fraude</SheetTitle>
            <SheetDescription>Dashboard del analista</SheetDescription>
          </SheetHeader>
          {enlaces}
          <div className="border-t p-3">{toggleTema}</div>
        </SheetContent>

        {/* Segunda región de scroll, independiente del `<aside>`: el shell
            entero queda fijo a la altura del viewport (`h-svh overflow-hidden`
            arriba) y sólo esto -el `<main>` de abajo- scrollea. */}
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <header className="flex shrink-0 items-center gap-3 border-b px-3 py-4 md:px-6">
            <SheetTrigger
              render={
                <Button variant="ghost" size="icon-sm" className="md:hidden" aria-label="Abrir navegación" />
              }
            >
              <MenuIcon />
            </SheetTrigger>
            <h1 className="text-xl font-semibold">{tituloDe(location.pathname)}</h1>
          </header>
          <main className="@container flex-1 overflow-y-auto overflow-x-auto px-2 py-4 md:px-6 md:py-6">
            <Outlet />
          </main>
        </div>
      </div>
    </Sheet>
  )
}
