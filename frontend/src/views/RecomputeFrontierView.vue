<template>
  <section class="page" data-module="recompute-frontier">
    <header class="page-head">
      <div>
        <h2>复算前沿</h2>
        <p class="page-desc">
          从血缘图选择变更表提交变更批，按下游血缘路径计算复算前沿；复算节点数据集逐表列出各派生表等待的分区。
        </p>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">变更批</span>
        <strong class="stat-value">{{ batches.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">可执行项（前沿）</span>
        <strong class="stat-value">{{ frontier.runnable_count }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">等待分区项</span>
        <strong class="stat-value">{{ frontier.waiting_count }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">晚到分区</span>
        <strong class="stat-value">{{ frontier.late_arrivals.length }}</strong>
      </article>
    </div>

    <form class="analysis-form" @submit.prevent="submitBatch">
      <label>
        变更表（血缘节点）
        <select v-model="form.node_id" data-testid="select-change-node" required>
          <option value="" disabled>请选择变更表</option>
          <option v-for="node in nodes" :key="node.node_id" :value="node.node_id">
            {{ node.node_name }}（{{ node.node_type }} · {{ node.owner }}）
          </option>
        </select>
      </label>
      <label>
        复算分区
        <input v-model="form.partitions" data-testid="input-partitions" placeholder="如 2026-11-19，多个用逗号分隔" required />
      </label>
      <label>
        变更原因
        <input v-model="form.reason" data-testid="input-reason" placeholder="如 订单批量订正" />
      </label>
      <button class="btn primary" data-testid="submit-batch" type="submit" :disabled="submitting">
        {{ submitting ? '提交中…' : '提交变更批' }}
      </button>
    </form>

    <p v-if="message" class="page-desc" data-testid="frontier-message">{{ message }}</p>

    <div v-if="frontier.late_arrivals.length" class="late-panel" data-testid="late-arrivals">
      <h3>晚到分区（送达后自动刷新前沿）</h3>
      <table class="data-table">
        <thead>
          <tr><th>上游节点</th><th>等待分区</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in frontier.late_arrivals" :key="`${item.node_id}-${item.partition}`">
            <td>{{ item.node_name }}</td>
            <td>{{ item.partition }}</td>
            <td>
              <button class="link" type="button" data-testid="deliver-partition"
                      @click="onDeliver(item.node_id, item.partition)">
                分区送达
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3>变更批与复算节点数据集</h3>
    <table class="data-table" data-testid="batch-table">
      <thead>
        <tr>
          <th>批次</th><th>变更表</th><th>复算分区</th><th>状态</th>
          <th>任务进度</th><th>可执行</th><th>变更原因</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="batch in batches" :key="batch.id" :data-testid="`batch-row-${batch.id}`">
          <td>#{{ batch.id }}</td>
          <td>{{ batch.source_node_name }}</td>
          <td>{{ batch.partitions.join('、') }}</td>
          <td>{{ batch.status }}</td>
          <td>{{ batch.done_count }}/{{ batch.task_count }}</td>
          <td>{{ batch.runnable_count }}</td>
          <td>{{ batch.reason }}</td>
          <td class="row-actions">
            <RouterLink class="link" :to="`/query_scheduler/recompute/${batch.id}`"
                        :data-testid="`open-schedule-${batch.id}`">
              调度详情
            </RouterLink>
          </td>
        </tr>
        <tr v-if="!batches.length">
          <td colspan="8" class="empty-state">暂无变更批，请先从血缘图选择变更表提交</td>
        </tr>
      </tbody>
    </table>

    <template v-if="frontier.frontier.length">
      <h3>复算前沿：可执行项（上游分区已齐）</h3>
      <table class="data-table" data-testid="frontier-runnable">
        <thead>
          <tr><th>变更批</th><th>派生表</th><th>等待分区</th><th>血缘路径</th><th>状态</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in frontier.frontier" :key="`${item.batch_id}-${item.node_id}-${item.partition}`">
            <td>#{{ item.batch_id }}</td>
            <td>{{ item.node_name }}</td>
            <td>{{ item.partition }}</td>
            <td>{{ item.lineage_path.join(' → ') }}</td>
            <td>可执行</td>
          </tr>
        </tbody>
      </table>
    </template>

    <template v-if="frontier.waiting.length">
      <h3>等待分区项（含欠缺的上游分区）</h3>
      <table class="data-table" data-testid="frontier-waiting">
        <thead>
          <tr><th>变更批</th><th>派生表</th><th>等待分区</th><th>欠缺的上游分区</th><th>血缘路径</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in frontier.waiting" :key="`${item.batch_id}-${item.node_id}-${item.partition}`">
            <td>#{{ item.batch_id }}</td>
            <td>{{ item.node_name }}</td>
            <td>{{ item.partition }}</td>
            <td>
              <span v-for="miss in item.missing_upstream" :key="miss.node_id" class="miss-tag">
                {{ miss.node_name }}[{{ miss.partition }}]
              </span>
            </td>
            <td>{{ item.lineage_path.join(' → ') }}</td>
          </tr>
        </tbody>
      </table>
    </template>

    <footer class="page-foot">
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'

import {
  deliverPartition,
  fetchBatches,
  fetchLineageNodes,
  submitChangeBatch,
  type ChangeBatch,
  type FrontierView,
  type LineageNodeOption,
} from '@/api/recompute'

const nodes = ref<LineageNodeOption[]>([])
const batches = ref<ChangeBatch[]>([])
const frontier = ref<FrontierView>({
  ok: true,
  batch_id: null,
  frontier: [],
  waiting: [],
  running: [],
  done: [],
  runnable_count: 0,
  waiting_count: 0,
  late_arrivals: [],
})
const form = reactive({ node_id: '', partitions: '', reason: '' })
const submitting = ref(false)
const message = ref('')
const errorMessage = ref('')

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await fetchBatches()
    batches.value = payload.items
    frontier.value = payload.frontier
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '复算前沿读取失败'
  }
}

async function submitBatch() {
  submitting.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    const partitions = form.partitions.split(',').map((item) => item.trim()).filter(Boolean)
    const result = await submitChangeBatch({
      node_id: form.node_id,
      partitions,
      reason: form.reason,
    })
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    form.partitions = ''
    form.reason = ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '变更批提交失败'
  } finally {
    submitting.value = false
  }
}

async function onDeliver(nodeId: string, partition: string) {
  errorMessage.value = ''
  try {
    const result = await deliverPartition(nodeId, partition)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '分区送达失败'
  }
}

onMounted(async () => {
  try {
    nodes.value = await fetchLineageNodes()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '血缘节点读取失败'
  }
  await reload()
})
</script>

<style scoped>
.late-panel {
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}
.late-panel h3 {
  margin: 0 0 8px;
  font-size: 14px;
}
.miss-tag {
  display: inline-block;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #b42318;
  border-radius: 4px;
  padding: 1px 6px;
  margin: 1px 4px 1px 0;
  font-size: 12px;
}
h3 {
  font-size: 15px;
  margin: 18px 0 8px;
}
</style>
