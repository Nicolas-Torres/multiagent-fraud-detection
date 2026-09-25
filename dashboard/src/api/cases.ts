import { api } from '@/api/client'
import type { components } from '@/api/schema'

type CaseDetail = components['schemas']['CaseDetail']

/**
 * El caso ya no existe (404). No es un error transitorio: no se reintenta ni
 * se sondea, y quien guardó su `case_id` tiene que olvidarlo.
 */
export class CasoNoEncontrado extends Error {
  readonly caseId: string

  constructor(caseId: string) {
    super(`el caso ${caseId} no existe`)
    this.name = 'CasoNoEncontrado'
    this.caseId = caseId
  }
}

export async function consultarCaso(caseId: string): Promise<CaseDetail> {
  const { data, error, response } = await api.GET('/api/v1/cases/{case_id}', {
    params: { path: { case_id: caseId } },
  })
  if (response.status === 404) throw new CasoNoEncontrado(caseId)
  if (error) throw error
  return data
}
