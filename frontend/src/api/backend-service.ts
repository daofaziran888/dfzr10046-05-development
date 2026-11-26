import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  EntryRow,
  OverviewResult,
  PageResult,
  RulingHistory,
  RulingTodos,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
  remark?: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action, remark: remark ?? null }),
  })
  return await response.json()
}

/** 维度建档待办：按原登记和核对轮次接收字段裁决结论。 */
export async function listRulingTodos(
  registration: string,
  roundNo?: string,
): Promise<RulingTodos> {
  const query = new URLSearchParams({ 原登记: registration })
  if (roundNo) query.set('核对轮次', roundNo)
  const response = await request(`/api/field_ruling/todos?${query.toString()}`)
  if (!response.ok) throw new Error('建档待办读取失败')
  return await response.json()
}

/** 按原登记查询已写入的名字和历轮意见。 */
export async function loadRulingHistory(registration: string): Promise<RulingHistory> {
  const query = new URLSearchParams({ 原登记: registration }).toString()
  const response = await request(`/api/field_ruling/history?${query}`)
  if (!response.ok) throw new Error('裁决历程读取失败')
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}
