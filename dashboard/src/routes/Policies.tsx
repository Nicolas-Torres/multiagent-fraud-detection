import { useQuery } from '@tanstack/react-query'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
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
  active: 'activa',
  excluded: 'excluida',
  pending: 'pendiente de vinculación',
  stale: 'vinculación obsoleta',
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
      <div>
        <h1 className="text-xl font-semibold">Catálogo de políticas</h1>
        <p className="text-sm text-muted-foreground">
          Sólo lectura esta etapa (ADR-0017) — el alta no está disponible todavía.
        </p>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : query.isError ? (
        <p className="text-destructive">No se pudo cargar el catálogo.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Versión</TableHead>
              <TableHead>Estado</TableHead>
              <TableHead>Acción</TableHead>
              <TableHead>Rule</TableHead>
              <TableHead>Detalle</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.map((p) => (
              <TableRow key={p.policy_id}>
                <TableCell className="font-medium">{p.policy_id}</TableCell>
                <TableCell className="text-muted-foreground">{p.version}</TableCell>
                <TableCell>
                  <Badge variant={STATE_VARIANT[p.state]}>{STATE_LABEL[p.state]}</Badge>
                </TableCell>
                <TableCell>{p.action ?? '—'}</TableCell>
                <TableCell className="max-w-md text-sm text-muted-foreground">{p.text}</TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.excluded_reason ?? (p.evaluable ? 'se evalúa' : '—')}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
