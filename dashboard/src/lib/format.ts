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
