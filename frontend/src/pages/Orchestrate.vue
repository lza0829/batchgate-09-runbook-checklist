<script setup>
import { computed, onMounted, ref } from 'vue'
import { deleteJSON, errorDetail, getJSON, patchJSON, postJSON } from '../api'

const state = ref(null)
const history = ref([])
const last = ref(null)
const busy = ref(false)
const err = ref('')
const notice = ref('')
const refusal = ref(null)
const newTitle = ref('')
const newRequired = ref(true)

const steps = computed(() => state.value?.steps || [])
const gate = computed(() => state.value?.gate || { can_start: false, reasons: [], counts: {}, consistent: true })
const batches = computed(() => state.value?.batches || [])
const events = computed(() => state.value?.events || [])
const label = computed(() => state.value?.label_map || {})
const counts = computed(() => gate.value.counts || {})

function statusClass(s) {
  return s === 'success' ? 'ok' : s === 'failed' ? 'danger' : s === 'skipped' ? 'warn' : ''
}

async function refresh() {
  state.value = await getJSON('/api/runbook')
  history.value = await getJSON('/api/orchestrations')
}

async function addStep() {
  err.value = ''
  const title = newTitle.value.trim()
  if (!title) return
  try {
    await postJSON('/api/runbook/steps', { title, required: newRequired.value })
    newTitle.value = ''
    await refresh()
  } catch (e) {
    err.value = errorDetail(e).message
  }
}

async function mark(step, status) {
  err.value = ''
  notice.value = ''
  try {
    await patchJSON(`/api/runbook/steps/${step.id}`, { status, note: step.note || '' })
    await refresh()
  } catch (e) {
    err.value = errorDetail(e).message
  }
}

async function removeStep(step) {
  err.value = ''
  try {
    await deleteJSON(`/api/runbook/steps/${step.id}`)
    await refresh()
  } catch (e) {
    err.value = errorDetail(e).message
  }
}

async function startRun() {
  err.value = ''
  notice.value = ''
  refusal.value = null
  busy.value = true
  try {
    last.value = await postJSON('/api/orchestrations')
    notice.value = `开跑成功：批次 ${last.value.runbook_batch_no} · 编排 #${last.value.id}`
    await refresh()
  } catch (e) {
    const parsed = errorDetail(e)
    err.value = parsed.message
    refusal.value = parsed.detail
    await refresh()
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    await refresh()
  } catch (e) {
    err.value = errorDetail(e).message
  }
})
</script>

<template>
  <div class="page">
    <h1>编排台</h1>
    <p class="muted">开跑前先过 Runbook 步骤队列：必做步骤全部成功才允许启动编排；拦截原因与放行批次都会留痕。</p>

    <p v-if="err" class="tag danger">{{ err }}</p>
    <p v-if="notice" class="tag ok">{{ notice }}</p>

    <div class="panel">
      <h3 style="margin-top:0">能否开跑</h3>
      <p>
        <span class="tag" :class="gate.can_start ? 'ok' : 'danger'">
          {{ gate.can_start ? '可以开跑' : '禁止开跑' }}
        </span>
        <span class="muted" style="margin-left:0.6rem">
          必做 {{ counts.required_done ?? 0 }}/{{ counts.required ?? 0 }} 完成 ·
          成功 {{ counts.success ?? 0 }} / 失败 {{ counts.failed ?? 0 }} /
          跳过 {{ counts.skipped ?? 0 }} / 待办 {{ counts.pending ?? 0 }}
          （合计 {{ counts.total ?? 0 }} 步）
        </span>
      </p>
      <p v-if="gate.reasons?.length" class="mono" style="color:var(--danger)">
        <span v-for="(r, i) in gate.reasons" :key="i">· {{ r }}<br /></span>
      </p>
      <button :disabled="busy" @click="startRun">
        {{ busy ? '编排中…' : '开跑' }}
      </button>
      <span v-if="!gate.can_start" class="muted" style="margin-left:0.6rem">
        当前点击会被服务端拦截，并记录一条 blocked 批次
      </span>
      <p v-if="refusal" class="mono muted" style="margin-bottom:0">
        拦截批次 {{ refusal.batch_no }} · decision={{ refusal.decision }} ·
        原因 {{ refusal.reasons?.length }} 条 · 编排未创建
      </p>
      <p v-if="refusal?.gate?.blocking_steps?.length" class="mono" style="color:var(--danger);margin-bottom:0">
        阻塞步骤：
        <span v-for="s in refusal.gate.blocking_steps" :key="s.id" class="tag danger" style="margin-right:0.3rem">
          {{ s.seq }} {{ s.title }}（{{ label[s.status] || s.status }}）
        </span>
      </p>
    </div>

    <div class="panel">
      <h3 style="margin-top:0">Runbook 步骤队列</h3>
      <p class="muted">
        按顺序推进：完成 {{ counts.success ?? 0 }} · 失败 {{ counts.failed ?? 0 }} ·
        跳过 {{ counts.skipped ?? 0 }} · 待办 {{ counts.pending ?? 0 }} = 合计 {{ counts.total ?? 0 }} 步
        <span class="tag" :class="gate.consistent ? 'ok' : 'danger'">
          {{ gate.consistent ? '账实一致' : '统计不一致' }}
        </span>
      </p>
      <table>
        <thead>
          <tr><th>#</th><th>步骤</th><th>必做</th><th>状态</th><th>备注</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="s in steps" :key="s.id">
            <td>{{ s.seq }}</td>
            <td>{{ s.title }}</td>
            <td><span class="tag" :class="s.required ? 'warn' : ''">{{ s.required ? '必做' : '可选' }}</span></td>
            <td><span class="tag" :class="statusClass(s.status)">{{ label[s.status] || s.status }}</span></td>
            <td><input v-model="s.note" style="width:9rem" placeholder="备注" /></td>
            <td>
              <button class="secondary" @click="mark(s, 'success')">完成</button>
              <button class="secondary" @click="mark(s, 'failed')" style="margin-left:0.35rem;background:var(--danger)">失败</button>
              <button v-if="!s.required" class="secondary" @click="mark(s, 'skipped')" style="margin-left:0.35rem">跳过</button>
              <button v-if="s.required" class="secondary" disabled title="必做步骤不可跳过" style="margin-left:0.35rem">跳过</button>
              <button class="secondary" @click="removeStep(s)" style="margin-left:0.35rem;background:#8a8f86">删除</button>
            </td>
          </tr>
          <tr v-if="!steps.length"><td colspan="6" class="muted">队列为空——没有步骤时不允许开跑。</td></tr>
        </tbody>
      </table>
      <div style="margin-top:0.75rem;display:flex;gap:0.5rem;align-items:center">
        <input v-model="newTitle" placeholder="新增步骤标题" style="flex:1" />
        <label class="muted"><input v-model="newRequired" type="checkbox" /> 必做</label>
        <button class="secondary" @click="addStep">添加步骤</button>
      </div>
    </div>

    <div class="panel" v-if="last">
      <h3>最近一次开跑</h3>
      <p>
        #{{ last.id }} · <span class="tag ok">{{ last.status }}</span> ·
        批次 <span class="mono">{{ last.runbook_batch_no }}</span> ·
        succeeded {{ last.report?.succeeded }} /
        failed {{ last.report?.failed }} /
        skipped {{ last.report?.skipped }} /
        attempts {{ last.report?.attempt_count }}
      </p>
      <p>
        <router-link :to="{ path: '/attempts', query: { orchestration_id: last.id } }">查看本次尝试 →</router-link>
        ·
        <router-link to="/watermarks">产出水位 →</router-link>
      </p>
    </div>

    <div class="panel">
      <h3>开跑批次（步骤快照）</h3>
      <table>
        <thead><tr><th>批次</th><th>决定</th><th>编排</th><th>步骤快照</th><th>原因</th><th>时间</th></tr></thead>
        <tbody>
          <tr v-for="b in batches" :key="b.id">
            <td class="mono">{{ b.batch_no }}</td>
            <td><span class="tag" :class="b.decision === 'allowed' ? 'ok' : 'danger'">{{ b.decision }}</span></td>
            <td>{{ b.orchestration_id ?? '—' }}</td>
            <td class="mono">
              <span v-for="(s, i) in b.snapshot" :key="s.id">
                <span :class="'tag ' + statusClass(s.status)">{{ s.seq }} {{ s.title }}</span>
                <span v-if="i < b.snapshot.length - 1"> → </span>
              </span>
            </td>
            <td class="mono" style="color:var(--danger)">{{ b.reasons?.join('；') || '—' }}</td>
            <td class="mono">{{ b.created_at }}</td>
          </tr>
          <tr v-if="!batches.length"><td colspan="6" class="muted">还没有开跑记录。</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h3>步骤变更记录</h3>
      <table>
        <thead><tr><th>时间</th><th>#</th><th>步骤</th><th>必做</th><th>变更</th><th>批次</th><th>备注</th></tr></thead>
        <tbody>
          <tr v-for="e in events" :key="e.id">
            <td class="mono">{{ e.created_at }}</td>
            <td>{{ e.seq }}</td>
            <td>{{ e.title }}</td>
            <td>{{ e.required ? '是' : '否' }}</td>
            <td class="mono">{{ e.from_status }} → {{ e.to_status }}</td>
            <td>{{ e.batch_id ?? '—' }}</td>
            <td class="muted">{{ e.note || '—' }}</td>
          </tr>
          <tr v-if="!events.length"><td colspan="7" class="muted">还没有步骤变更。</td></tr>
        </tbody>
      </table>
    </div>

    <div class="panel">
      <h3>历史编排</h3>
      <table>
        <thead><tr><th>ID</th><th>状态</th><th>批次</th><th>成功</th><th>失败</th><th>跳过</th><th>开始</th></tr></thead>
        <tbody>
          <tr v-for="o in history" :key="o.id">
            <td>{{ o.id }}</td>
            <td>{{ o.status }}</td>
            <td class="mono">{{ o.runbook_batch_no || '—' }}</td>
            <td>{{ o.report?.succeeded }}</td>
            <td>{{ o.report?.failed }}</td>
            <td>{{ o.report?.skipped }}</td>
            <td class="mono">{{ o.started_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
