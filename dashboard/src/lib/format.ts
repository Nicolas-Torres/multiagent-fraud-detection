// `amount` llega como string (serialización de `Decimal`, contrato §2.6) —
// nunca se convierte a `Number`, ni siquiera para mostrarlo: separadores de
// miles se insertan sobre el string. Perder un centavo por redondeo binario
// es exactamente lo que la frontera evita al no usar `float`.
export function formatAmount(amount: string, currency?: string): string {
  const negativo = amount.startsWith('-')
  const [entero, decimales = '00'] = (negativo ? amount.slice(1) : amount).split('.')
  const conSeparadores = entero.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  const monto = `${negativo ? '-' : ''}${conSeparadores}.${decimales}`
  return currency ? `${currency} ${monto}` : monto
}

export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat('es', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso))
}

// Sólo cosmético: el id real de una corrida en vivo (`LIVE-approve-171...`)
// sigue siendo el que viaja a la API y al link del caso -esto nunca lo
// reemplaza-, pero como valor de columna se ve como ruido al lado de
// "T-2579". Se homogeneiza al mismo formato tomando los últimos 4 dígitos
// del token que generó la corrida (siempre al final del id, sin importar
// si el escenario mismo trae dígitos como `t1012`).
export function formatTransactionId(id: string): string {
  if (!id.startsWith('LIVE-')) return id
  const digitos = id.replace(/\D/g, '')
  return `T-${digitos.slice(-4).padStart(4, '0')}`
}
