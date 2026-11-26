/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}

/** 字段裁决待办行：维度建档按原登记和核对轮次接收到的裁决。 */
export type RulingRow = {
  id: number
  status: string
  裁决编号: string
  核对编号: string
  原登记: string
  核对轮次: string
  裁决字段: string
  基准值: string
  对照值: string
  裁决结论: string
  裁决时间: string
}

export type RulingTodos = {
  原登记: string
  核对轮次: string | null
  待办: RulingRow[]
  允许改正字段: string[]
}

export type RulingOpinion = {
  时间: string
  操作者: string
  环节: string
  意见: string
}

export type RulingWritten = {
  裁决编号: string
  裁决字段: string
  旧值: string
  新值: string
  核对轮次: string
  写入时间: string
}

export type RulingRound = {
  裁决编号: string
  核对轮次: string
  裁决字段: string
  裁决结论: string
  当前状态: string
  意见记录: RulingOpinion[]
}

export type RulingHistory = {
  原登记: string
  已写入: RulingWritten[]
  历轮意见: RulingRound[]
}
