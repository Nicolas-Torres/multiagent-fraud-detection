import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api } from '@/api/client'
import type { components } from '@/api/schema'
import { Badge } from '@/components/ui/badge'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { decisionVariant } from '@/lib/badges'
import { formatAmount, formatDateTime } from '@/lib/format'

type CaseStatus = components['schemas']['CaseStatus']

const STATUSES: CaseStatus[] = [
  'RECEIVED',
  'ANALYZING',
  'DECIDED',
  'PENDING_HUMAN',
  'RESOLVED',
  'FAILED',
]

// Contrato §5 decisión 3: polling, nunca WebSocket. 8s balancea "se ve vivo"
// contra no saturar la API con un intervalo agresivo.
const POLL_MS = 8_000

export function Queue() {
  const [status, setStatus] = useState<CaseStatus | 'ALL'>('PENDING_HUMAN')
  const navigate = useNavigate()

  const query = useQuery({
    queryKey: ['cases', status],
    queryFn: async () => {
      const { data, error } = await api.GET('/api/v1/cases', {
        params: {
          query: {
            status: status === 'ALL' ? undefined : status,
            limit: 50,
          },
        },
      })
      if (error) throw error
      return data
    },
    refetchInterval: POLL_MS,
  })

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Select value={status} onValueChange={(v) => setStatus(v as CaseStatus | 'ALL')}>
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="ALL">Todos los estados</SelectItem>
            {STATUSES.map((s) => (
              <SelectItem key={s} value={s}>
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-64 w-full" />
      ) : query.isError ? (
        <p className="text-destructive">No se pudo cargar la cola.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Estado</TableHead>
              <TableHead>Veredicto</TableHead>
              <TableHead>Confianza</TableHead>
              <TableHead>Monto</TableHead>
              <TableHead>Cliente</TableHead>
              <TableHead>Creado</TableHead>
              <TableHead>Acciones</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.data?.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground">
                  Sin casos para este filtro.
                </TableCell>
              </TableRow>
            )}
            {query.data?.items.map((item) => (
              <TableRow
                key={item.case_id}
                className="cursor-pointer"
                onClick={() => navigate(`/cases/${item.case_id}`)}
              >
                <TableCell>
                  <Badge variant="outline">{item.status}</Badge>
                </TableCell>
                <TableCell>
                  {item.decision ? (
                    <Badge variant={decisionVariant(item.decision)}>{item.decision}</Badge>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
                <TableCell>{item.confidence ?? '—'}</TableCell>
                <TableCell>{formatAmount(item.amount)}</TableCell>
                <TableCell>{item.customer_id}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(item.created_at)}
                </TableCell>
                <TableCell>
                  {item.status === 'PENDING_HUMAN' ? (
                    <Badge variant="default">Revisar</Badge>
                  ) : (
                    <Badge variant="secondary">Revisado</Badge>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
