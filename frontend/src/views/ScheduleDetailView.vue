<template>
  <section class="page" data-module="recompute-schedule">
    <header class="page-head">
      <div>
        <h2>调度详情 · 变更批 #{{ batchId }}</h2>
        <p class="page-desc">
          排程接收复算节点数据集，逐表列出可执行项与欠缺的上游分区；缺任一上游分区时派生表不得提前产出。
        </p>
      </div>
      <div class="page-actions">
        <RouterLink class="btn" to="/recompute-frontier">返回复算前沿</RouterLink>
      </div>
    </header>

    <div v-if="detail" class="batch-meta" data-testid="batch-meta">
      <span>变更表：<strong>{{ detail.batch.source_node_name }}</strong></span>
      <span>复算分区：{{ detail.batch.partitions.join('、') }}</span>
      <span>批次状态：{{ detail.batch.status }}</span>
      <span>进度：{{ detail.batch.done_count }}/{{ detail.batch.task_count }}</span>
      <span>原因：{{ detail.batch.reason }}</span>
    </div>

    <p v-if="message" class="page-desc" data-testid="schedule-message">{{ message }}</p>
    <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

    <div v-if="detail?.late_arrivals.length" class="late-panel">
      <h3>晚到分区（外部上游未送达）</h3>
      <table class="data-table">
        <thead>
          <tr><th>上游节点</th><th>等待分区</th><th>操作</th></tr>
        </thead>
        <tbody>
          <tr v-for="item in detail.late_arrivals" :key="`${item.node_id}-${item.partition}`">
            <td>{{ item.node_name }}</td>
            <td>{{ item.partition }}</td>
            <td>
              <button class="link" type="button" :data-testid="`deliver-${item.node_id}`"
                      @click="onDeliver(item.node_id, item.partition)">
                分区送达
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <h3>可执行项（复算前沿，上游分区已齐）</h3>
    <table class="data-table" data-testid="runnable-table">
      <thead>
        <tr><th>派生表</th><th>等待分区</th><th>血缘路径</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="task in detail?.runnable_tables ?? []" :key="task.node_id">
          <td>{{ task.node_name }}</td>
          <td>{{ task.partition }}</td>
          <td>{{ task.lineage_path.join(' → ') }}</td>
          <td>
            <button class="link" type="button" :data-testid="`start-${task.node_id}`"
                    @click="onStart(task.node_id, task.partition)">
              本轮开跑
            </button>
          </td>
        </tr>
        <tr v-if="!(detail?.runnable_tables.length)">
          <td colspan="4" class="empty-state">当前没有可执行项，全部派生表仍在等待上游分区</td>
        </tr>
      </tbody>
    </table>

    <h3>执行中</h3>
    <table class="data-table" data-testid="running-table">
      <thead>
        <tr><th>派生表</th><th>分区</th><th>血缘路径</th><th>操作</th></tr>
      </thead>
      <tbody>
        <tr v-for="task in detail?.running_tables ?? []" :key="task.node_id">
          <td>{{ task.node_name }}</td>
          <td>{{ task.partition }}</td>
          <td>{{ task.lineage_path.join(' → ') }}</td>
          <td>
            <button class="link" type="button" :data-testid="`complete-${task.node_id}`"
                    @click="onComplete(task.node_id, task.partition)">
              登记完成（分区可读取）
            </button>
          </td>
        </tr>
        <tr v-if="!(detail?.running_tables.length)">
          <td colspan="4" class="empty-state">暂无执行中的复算项</td>
        </tr>
      </tbody>
    </table>

    <h3>等待分区（欠缺的上游分区已逐项标出）</h3>
    <table class="data-table" data-testid="waiting-table">
      <thead>
        <tr><th>派生表</th><th>等待分区</th><th>欠缺的上游分区</th><th>血缘路径</th></tr>
      </thead>
      <tbody>
        <tr v-for="task in detail?.waiting_tables ?? []" :key="task.node_id"
            :data-testid="`waiting-row-${task.node_id}`">
          <td>{{ task.node_name }}</td>
          <td>{{ task.partition }}</td>
          <td>
            <span v-for="miss in task.missing_upstream" :key="miss.node_id" class="miss-tag">
              {{ miss.node_name }}[{{ miss.partition }}]
            </span>
          </td>
          <td>{{ task.lineage_path.join(' → ') }}</td>
        </tr>
        <tr v-if="!(detail?.waiting_tables.length)">
          <td colspan="4" class="empty-state">没有等待中的复算项</td>
        </tr>
      </tbody>
    </table>

    <h3>已完成（分区可读取）</h3>
    <table class="data-table" data-testid="done-table">
      <thead>
        <tr><th>派生表</th><th>分区</th><th>血缘路径</th></tr>
      </thead>
      <tbody>
        <tr v-for="task in detail?.completed_tables ?? []" :key="task.node_id"
            :data-testid="`done-row-${task.node_id}`">
          <td>{{ task.node_name }}</td>
          <td>{{ task.partition }}</td>
          <td>{{ task.lineage_path.join(' → ') }}</td>
        </tr>
        <tr v-if="!(detail?.completed_tables.length)">
          <td colspan="3" class="empty-state">暂无已完成复算项</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span v-if="summaryState">
        经营汇总（ads_business_summary）当前状态：<strong data-testid="summary-state">{{ summaryState }}</strong>
        <template v-if="summaryState === '已完成'">，分区已可读取</template>
      </span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'

import {
  completeTask,
  deliverPartition,
  fetchScheduleDetail,
  startTask,
  type ScheduleDetail,
} from '@/api/recompute'

const route = useRoute()
const batchId = Number(route.params.batchId)
const detail = ref<ScheduleDetail | null>(null)
const message = ref('')
const errorMessage = ref('')

const summaryState = computed(() => {
  const all = detail.value ? [
    ...detail.value.runnable_tables,
    ...detail.value.waiting_tables,
    ...detail.value.running_tables,
    ...detail.value.completed_tables,
  ] : []
  return all.find((task) => task.node_name === 'ads_business_summary')?.state ?? ''
})

async function reload() {
  errorMessage.value = ''
  try {
    detail.value = await fetchScheduleDetail(batchId)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '调度详情读取失败'
  }
}

async function onStart(nodeId: string, partition: string) {
  errorMessage.value = ''
  try {
    const result = await startTask(batchId, nodeId, partition)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '开跑失败'
  }
}

async function onComplete(nodeId: string, partition: string) {
  errorMessage.value = ''
  try {
    const result = await completeTask(batchId, nodeId, partition)
    if (!result.ok) throw new Error(result.message)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记完成失败'
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

onMounted(reload)
</script>

<style scoped>
.batch-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  font-size: 13px;
}
.late-panel {
  background: #fff7ed;
  border: 1px solid #fdba74;
  border-radius: 8px;
  padding: 12px;
  margin: 16px 0;
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
