<script setup>
import { onMounted, ref } from 'vue'
import { getJSON } from '../api'
const stats = ref(null)
const err = ref('')
onMounted(async () => {
  try { stats.value = await getJSON('/api/dashboard') } catch (e) { err.value = String(e.message || e) }
})
</script>
<template>
  <div class="page">
    <h1>总览</h1>
    <p class="muted">离线作业依赖编排：看作业数、编排次数与已写出水位的作业数。</p>
    <p v-if="err" class="tag danger">{{ err }}</p>
    <div class="panel" v-if="stats">
      <p>作业 {{ stats.job_count }}（启用 {{ stats.enabled_jobs }}）</p>
      <p>编排 {{ stats.orchestration_count }} · 尝试 {{ stats.attempt_count }}</p>
      <p>已有水位的作业 {{ stats.watermarked_jobs }}</p>
    </div>
    <div class="panel" v-if="stats">
      <h3 style="margin-top:0">Runbook 闸门</h3>
      <p>
        <span class="tag" :class="stats.runbook_can_start ? 'ok' : 'danger'">
          {{ stats.runbook_can_start ? '可开跑' : '禁止开跑' }}
        </span>
        <span class="muted" style="margin-left:0.6rem">
          必做 {{ stats.runbook_counts?.required_done }}/{{ stats.runbook_counts?.required }} ·
          待办 {{ stats.runbook_counts?.pending }}
        </span>
      </p>
      <p v-if="!stats.runbook_can_start" class="mono muted">{{ stats.runbook_reasons?.join('；') }}</p>
      <router-link to="/orchestrate">去编排台处理步骤 →</router-link>
    </div>
  </div>
</template>
