import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { DecisionBadge } from '@/components/DecisionBadge'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

type PolicyState = components['schemas']['PolicyState']
type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline'

const STATE_LABEL: Record<PolicyState, string> = {
  active: 'Activa',
  excluded: 'Excluida',
  pending: 'Pendiente de vinculación',
  stale: 'Vinculación obsoleta',
}

const STATE_VARIANT: Record<PolicyState, BadgeVariant> = {
  active: 'secondary',
  excluded: 'destructive',
  pending: 'outline',
  stale: 'outline',
}

export function Policies() {
  const query = useQuery({
    queryKey: ['policies'],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/policies')
      if (error) throw error
      return data
    },
  })

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Las políticas del banco en su forma ejecutable: se evalúan con reglas
        determinísticas, no con un LLM, y fijan el veredicto mínimo de cada caso.
      </p>

      {query.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : query.isError ? (
        <p className="text-destructive">No se pudo cargar el catálogo.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead className="hidden @3xl:table-cell">Versión</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead className="hidden @3xl:table-cell">Acción</TableHead>
              <TableHead>Rule</TableHead>
              <TableHead className="hidden @3xl:table-cell">Detalle</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.map((p) => (
              <TableRow key={p.policy_id}>
                <TableCell className="font-medium">{p.policy_id}</TableCell>
                <TableCell className="hidden text-muted-foreground @3xl:table-cell">
                  {p.version}
                </TableCell>
                <TableCell>
                  <Badge
                    variant={STATE_VARIANT[p.state]}
                    className={p.state === 'active' ? 'border' : undefined}
                    style={
                      p.state === 'active'
                        ? {
                            backgroundColor: 'var(--decision-approve-bg)',
                            color: 'var(--decision-approve-fg)',
                            borderColor: 'var(--decision-approve-fg)',
                          }
                        : undefined
                    }
                  >
                    {STATE_LABEL[p.state]}
                  </Badge>
                </TableCell>
                <TableCell className="hidden @3xl:table-cell">
                  {p.action ? <DecisionBadge decision={p.action} compacto /> : '—'}
                </TableCell>
                <TableCell className="whitespace-normal text-sm text-muted-foreground">
                  {p.text}
                </TableCell>
                <TableCell className="hidden @3xl:table-cell">
                  {p.excluded_reason ?? (p.evaluable ? 'Se evalúa' : '—')}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
