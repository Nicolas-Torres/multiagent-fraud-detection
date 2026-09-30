import type { components } from '@/api/schema'
import { CLAVE_COLOR_DECISION, ETIQUETA_DECISION } from '@/lib/etiquetas'
import { cn } from '@/lib/utils'

type DecisionType = components['schemas']['DecisionType']

/**
 * La decisión con su color (mejoras2): verde, amarillo, azul o rojo, en claro
 * y en oscuro, desde las variables de `index.css`. `compacto` permite partir
 * la etiqueta en dos líneas para que entre en una columna angosta.
 */
export function DecisionBadge({
  decision,
  compacto = false,
  className,
}: {
  decision: DecisionType
  compacto?: boolean
  className?: string
}) {
  const clave = CLAVE_COLOR_DECISION[decision]
  return (
    <span
      className={cn(
        'inline-flex w-fit items-center rounded-md border px-2 py-0.5 text-xs font-medium leading-tight',
        compacto ? 'max-w-[7.5rem] whitespace-normal text-left' : 'whitespace-nowrap',
        className,
      )}
      style={{
        backgroundColor: `var(--decision-${clave}-bg)`,
        color: `var(--decision-${clave}-fg)`,
        borderColor: `var(--decision-${clave}-fg)`,
      }}
    >
      {ETIQUETA_DECISION[decision]}
    </span>
  )
}
