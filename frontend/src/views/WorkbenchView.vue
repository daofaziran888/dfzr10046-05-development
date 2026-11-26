<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <section v-if="meta.key === 'dim_entry'" class="ruling-panel" data-testid="ruling-todo-panel">
      <h3>字段裁决待办（一致性核对结论同步）</h3>
      <form class="filter-bar" @submit.prevent="loadTodos">
        <label class="filter-item">
          <span>原登记（维度编号）</span>
          <input v-model="todoRegistration" data-testid="todo-registration" placeholder="如 DIM-001" />
        </label>
        <label class="filter-item">
          <span>核对轮次</span>
          <input v-model="todoRound" data-testid="todo-round" placeholder="可空，默认全部轮次" />
        </label>
        <button class="btn" data-testid="todo-query" type="submit">接收待办</button>
      </form>
      <template v-if="todoLoaded">
        <p class="ruling-hint">
          允许改正的字段范围（由已签收结论判定）：{{ todoAllowed.length ? todoAllowed.join('、') : '暂无' }}
        </p>
        <table v-if="todoRows.length" class="data-table">
          <thead>
            <tr>
              <th>裁决编号</th><th>核对轮次</th><th>裁决字段</th><th>裁决结论</th>
              <th>基准值</th><th>对照值</th><th>当前状态</th><th>可执行动作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="todo in todoRows" :key="todo.id" :data-testid="`todo-${todo.id}`">
              <td>{{ todo.裁决编号 }}</td>
              <td>{{ todo.核对轮次 }}</td>
              <td>{{ todo.裁决字段 }}</td>
              <td>{{ todo.裁决结论 }}</td>
              <td>{{ todo.基准值 || '—' }}</td>
              <td>{{ todo.对照值 || '—' }}</td>
              <td>{{ todo.status }}</td>
              <td class="row-actions">
                <button
                  v-if="todo.status === '待签收'"
                  class="link"
                  type="button"
                  :data-testid="`todo-sign-${todo.id}`"
                  @click="runTodoAction('签收裁决', todo)"
                >
                  签收裁决
                </button>
                <button
                  v-if="todo.status === '已签收'"
                  class="link"
                  type="button"
                  :data-testid="`todo-apply-${todo.id}`"
                  @click="runTodoAction('写入改正', todo)"
                >
                  写入改正
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="ruling-hint">该原登记当前没有生效中的字段裁决待办。</p>
      </template>
    </section>

    <section v-if="meta.key === 'field_ruling'" class="ruling-panel" data-testid="ruling-history-panel">
      <h3>按原登记查询写入与历轮意见</h3>
      <form class="filter-bar" @submit.prevent="loadHistory">
        <label class="filter-item">
          <span>原登记（维度编号）</span>
          <input v-model="historyRegistration" data-testid="history-registration" placeholder="如 DIM-001" />
        </label>
        <button class="btn" data-testid="history-query" type="submit">查询历程</button>
      </form>
      <template v-if="historyLoaded">
        <h4>已写入的名字</h4>
        <table v-if="historyWritten.length" class="data-table">
          <thead>
            <tr><th>裁决编号</th><th>裁决字段</th><th>旧值</th><th>新值</th><th>核对轮次</th><th>写入时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="item in historyWritten" :key="item.裁决编号">
              <td>{{ item.裁决编号 }}</td>
              <td>{{ item.裁决字段 }}</td>
              <td>{{ item.旧值 }}</td>
              <td>{{ item.新值 }}</td>
              <td>{{ item.核对轮次 }}</td>
              <td>{{ item.写入时间 }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="ruling-hint">暂无已写入的改正。</p>
        <h4>历轮意见</h4>
        <div
          v-for="round in historyRounds"
          :key="round.裁决编号"
          class="ruling-round"
          :data-testid="`round-${round.裁决编号}`"
        >
          <p class="ruling-round-head">
            {{ round.裁决编号 }} · 第{{ round.核对轮次 }}轮 · {{ round.裁决字段 }} ·
            {{ round.裁决结论 }} · 当前状态：{{ round.当前状态 }}
          </p>
          <ul>
            <li v-for="(opinion, idx) in round.意见记录" :key="idx">
              [{{ opinion.时间 }}] {{ opinion.环节 }}（{{ opinion.操作者 }}）：{{ opinion.意见 }}
            </li>
          </ul>
        </div>
        <p v-if="!historyRounds.length" class="ruling-hint">该原登记暂无裁决历程。</p>
      </template>
    </section>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import {
  createEntry,
  downloadEntries,
  listEntries,
  listRulingTodos,
  loadRulingHistory,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import type { EntryRow, RulingRound, RulingRow, RulingWritten } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})
const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => row.status === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  let remark: string | undefined
  if (meta.key === 'field_ruling' && action === '写入改正' && row['裁决结论'] === '退回') {
    remark = askCorrectionValue(String(row['裁决编号']), String(row['裁决字段']))
    if (remark === undefined) return
  }
  try {
    const result = await applyAction(meta.key, Number(row.id), action, remark)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

/** 退回字段写入改正时必须提供改正值；取消输入则放弃本次写入。 */
function askCorrectionValue(code: string, field: string): string | undefined {
  const value = window.prompt(`裁决 ${code} 已退回字段「${field}」，请输入改正值`)
  return value === null ? undefined : value.trim()
}

const todoRegistration = ref('')
const todoRound = ref('')
const todoRows = ref<RulingRow[]>([])
const todoAllowed = ref<string[]>([])
const todoLoaded = ref(false)
const historyRegistration = ref('')
const historyWritten = ref<RulingWritten[]>([])
const historyRounds = ref<RulingRound[]>([])
const historyLoaded = ref(false)

async function loadTodos() {
  const registration = todoRegistration.value.trim()
  if (!registration) return
  errorMessage.value = ''
  try {
    const payload = await listRulingTodos(registration, todoRound.value.trim() || undefined)
    todoRows.value = payload.待办
    todoAllowed.value = payload.允许改正字段
    todoLoaded.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '建档待办读取失败'
  }
}

async function runTodoAction(action: string, todo: RulingRow) {
  errorMessage.value = ''
  let remark: string | undefined
  if (action === '写入改正' && todo.裁决结论 === '退回') {
    remark = askCorrectionValue(todo.裁决编号, todo.裁决字段)
    if (remark === undefined) return
  }
  try {
    const result = await applyAction('field_ruling', todo.id, action, remark)
    if (!result.ok) throw new Error(result.message)
    await Promise.all([reload(), loadTodos()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function loadHistory() {
  const registration = historyRegistration.value.trim()
  if (!registration) return
  errorMessage.value = ''
  try {
    const payload = await loadRulingHistory(registration)
    historyWritten.value = payload.已写入
    historyRounds.value = payload.历轮意见
    historyLoaded.value = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '裁决历程读取失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
    if (meta.key === 'dim_entry' && !todoRegistration.value && rows.value.length) {
      todoRegistration.value = String(rows.value[0]['维度编号'] ?? '')
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

onMounted(reload)
</script>
