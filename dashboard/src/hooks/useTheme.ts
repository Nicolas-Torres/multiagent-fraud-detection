import { useEffect, useState } from 'react'

type Tema = 'light' | 'dark'

const STORAGE_KEY = 'tema'

function leerTemaInicial(): Tema {
  try {
    const guardado = localStorage.getItem(STORAGE_KEY)
    if (guardado === 'light' || guardado === 'dark') return guardado
  } catch {
    // localStorage inaccesible (modo privado estricto, etc.) — cae al claro.
  }
  return 'light'
}

/**
 * `index.css` ya trae la paleta oscura completa (`.dark { ... }`, shadcn) —
 * esto sólo alterna la clase en `<html>` y persiste la elección. Sin
 * `prefers-color-scheme`: la elección del visitante manda siempre, no el
 * sistema operativo.
 */
export function useTheme(): [Tema, () => void] {
  const [tema, setTema] = useState<Tema>(leerTemaInicial)

  useEffect(() => {
    document.documentElement.classList.toggle('dark', tema === 'dark')
    try {
      localStorage.setItem(STORAGE_KEY, tema)
    } catch {
      // sin persistencia disponible — el toggle sigue funcionando en memoria
    }
  }, [tema])

  function alternar() {
    setTema((actual) => (actual === 'dark' ? 'light' : 'dark'))
  }

  return [tema, alternar]
}
