import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '@/api/client'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

interface ResolutionFormProps {
  caseId: string
}

// Sin sesión del analista todavía (deuda declarada, acta 09 §6.1): el
// identificador es de quien usa el dashboard hoy, no un login real.
const ANALYST_ID = 'analyst-dashboard'

export function ResolutionForm({ caseId }: ResolutionFormProps) {
  const [notes, setNotes] = useState('')
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: async (action: 'APPROVE' | 'REJECT') => {
      const { data, error } = await api.POST('/api/v1/cases/{case_id}/resolution', {
        params: { path: { case_id: caseId } },
        body: { action, analyst_id: ANALYST_ID, notes: notes || null },
      })
      if (error) throw error
      return data
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['case', caseId] })
      queryClient.invalidateQueries({ queryKey: ['cases'] })
    },
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Acción del analista</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Textarea
          placeholder="Notas (opcional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          disabled={mutation.isPending}
        />
        <div className="flex gap-2">
          <Button onClick={() => mutation.mutate('APPROVE')} disabled={mutation.isPending}>
            Aprobar
          </Button>
          <Button
            variant="destructive"
            onClick={() => mutation.mutate('REJECT')}
            disabled={mutation.isPending}
          >
            Rechazar
          </Button>
        </div>
        {mutation.isError && (
          <p className="text-sm text-destructive">No se pudo registrar la resolución.</p>
        )}
      </CardContent>
    </Card>
  )
}
