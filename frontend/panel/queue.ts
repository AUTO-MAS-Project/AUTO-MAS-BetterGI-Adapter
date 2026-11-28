import type { Value } from './bridge'

export const builtins = {
  领取邮件: 'bettergiGroupMail',
  领取尘歌壶奖励: 'bettergiGroupTeapot',
  合成树脂: 'bettergiGroupResin',
  自动幽境危战: 'bettergiGroupStygian',
  自动地脉花: 'bettergiGroupLeyLine',
  自动首领讨伐: 'bettergiGroupBoss',
  自动秘境: 'bettergiGroupDomain',
  领取每日奖励: 'bettergiGroupDailyReward',
}

export const combat = new Set(['自动秘境', '自动地脉花', '自动首领讨伐', '自动幽境危战'])
export type Kind = 'builtin' | 'custom' | 'js' | 'pathing' | 'scriptgroup' | 'keymouse'
export type Entry = {
  uid: number
  kind: Kind
  name: string
  displayName?: string
  suffix?: string
  planUid?: string
  step?: string
  enabled?: boolean
}
export type Group = { name: string; enabled: boolean }
export type Step = { name: string; uid: string; enabled: boolean }

export function parseList<T>(raw: Value | undefined): T[] {
  const data: unknown = typeof raw === 'string' && raw ? JSON.parse(raw) : raw
  return Array.isArray(data) ? data : []
}

export function planSteps(raw: string): Step[] {
  const plan = raw ? JSON.parse(raw) : null
  return Array.isArray(plan) ? plan : (plan?.steps ?? [])
}

export function stepName(row: Entry, rows: Entry[], steps: Step[]) {
  const bound = steps.find(step => step.uid === row.planUid)
  if (bound) return bound.name
  if (row.step) return row.step
  const first = rows
    .filter(item => item.name === row.name && item.kind === row.kind)
    .every(item => item.uid >= row.uid)
  return first ? row.name : `${row.name}-${row.uid}`
}

export function move<T>(items: T[], from: number, to: number) {
  const next = items.slice()
  next.splice(to, 0, ...next.splice(from, 1))
  return next
}
