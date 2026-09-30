import type { components } from '@/api/schema'

type Severity = components['schemas']['Severity']
type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline'

export function severityVariant(severity: Severity): BadgeVariant {
  switch (severity) {
    case 'low':
      return 'secondary'
    case 'medium':
      return 'default'
    case 'high':
      return 'destructive'
  }
}
