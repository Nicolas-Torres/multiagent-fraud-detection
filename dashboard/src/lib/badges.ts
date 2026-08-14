import type { components } from '@/api/schema'

type DecisionType = components['schemas']['DecisionType']
type Severity = components['schemas']['Severity']
type BadgeVariant = 'default' | 'secondary' | 'destructive' | 'outline'

export function decisionVariant(decision: DecisionType): BadgeVariant {
  switch (decision) {
    case 'APPROVE':
      return 'secondary'
    case 'CHALLENGE':
      return 'default'
    case 'BLOCK':
      return 'destructive'
    case 'ESCALATE_TO_HUMAN':
      return 'outline'
  }
}

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
