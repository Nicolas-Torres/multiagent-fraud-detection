import { useEffect, useState } from 'react'

/** Punto de corte único para nav (sidebar↔sheet) y grafo (horizontal↔vertical). */
export const MOBILE_BREAKPOINT_PX = 768

function calcularEsMobile(): boolean {
  if (typeof window === 'undefined') return false
  return window.innerWidth < MOBILE_BREAKPOINT_PX
}

/**
 * Sigue el mismo patrón que `useTheme`: `matchMedia` en vez de
 * `localStorage`, pero mismo `useState` + `useEffect` con listener.
 */
export function useIsMobile(): boolean {
  const [esMobile, setEsMobile] = useState<boolean>(calcularEsMobile)

  useEffect(() => {
    const media = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT_PX - 1}px)`)
    const actualizar = () => setEsMobile(media.matches)
    actualizar()
    media.addEventListener('change', actualizar)
    return () => media.removeEventListener('change', actualizar)
  }, [])

  return esMobile
}
