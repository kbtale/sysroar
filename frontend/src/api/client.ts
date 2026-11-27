import axios from 'axios'
import type { components } from './schema'

axios.defaults.withCredentials = true
axios.defaults.xsrfCookieName = 'csrftoken'
axios.defaults.xsrfHeaderName = 'X-CSRFToken'

export type ServerRecord = components['schemas']['Server']
export type AlertRuleRecord = components['schemas']['AlertRule']
export type NotificationChannelRecord = components['schemas']['NotificationChannel']
export type IncidentRecord = components['schemas']['Incident']
export type IncidentCommentRecord = components['schemas']['IncidentComment']
export type AlertSilenceRecord = components['schemas']['AlertSilence']
export type EnrollmentTokenRecord = components['schemas']['EnrollmentToken']
export type AgentKeyRecord = components['schemas']['AgentKey']
export type AuditLogRecord = components['schemas']['AuditLog']
export type CompanyRecord = components['schemas']['Company']
export type CompanyMemberRecord = components['schemas']['CompanyMember']
export type CompanyInviteRecord = components['schemas']['CompanyInvite']
export type MetricHistoryResponse = components['schemas']['ServerMetricsHistoryResponse']
export type MetricHistoryPoint = components['schemas']['MetricHistoryPoint']

export interface PaginatedResponse<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export function unwrapResults<T>(payload: PaginatedResponse<T> | T[]): T[] {
  if (Array.isArray(payload)) {
    return payload
  }
  return payload.results ?? []
}

export function extractApiError(error: unknown, fallback = 'Request failed. Please try again.'): string {
  if (axios.isAxiosError(error)) {
    const data = error.response?.data
    if (typeof data === 'string' && data.trim()) {
      return data
    }
    if (data && typeof data === 'object') {
      const record = data as Record<string, unknown>
      if (typeof record.error === 'string') {
        return record.error
      }
      if (typeof record.detail === 'string') {
        return record.detail
      }
      for (const value of Object.values(record)) {
        if (Array.isArray(value) && typeof value[0] === 'string') {
          return value[0]
        }
        if (typeof value === 'string') {
          return value
        }
      }
    }
  }
  return fallback
}

export const api = axios
