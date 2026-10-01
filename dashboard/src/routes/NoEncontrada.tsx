import { Link } from 'react-router-dom'

/**
 * Una URL que no es de ninguna vista. Sin esto, React Router mostraba su
 * pantalla de error de desarrollo ("Unexpected Application Error! 404"),
 * fuera del shell y sin forma de volver.
 */
export function NoEncontrada() {
  return (
    <div className="space-y-2">
      <p>Esta página no existe.</p>
      <Link to="/" className="text-sm text-muted-foreground hover:underline">
        ← Volver al inicio
      </Link>
    </div>
  )
}
