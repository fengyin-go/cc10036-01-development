/** 复算编排接口：变更批、复算前沿、调度详情、分区送达。 */
import { fetchJson, request } from './client'

export type MissingUpstream = {
  node_id: string
  node_name: string
  partition: string
}

export type RecomputeTask = {
  node_id: string
  node_name: string
  node_type: string
  partition: string
  lineage_path: string[]
  missing_upstream: MissingUpstream[]
  state: string
  ready: boolean
}

export type ChangeBatch = {
  id: number
  source_node_id: string
  source_node_name: string
  partitions: string[]
  reason: string
  created_at: string
  status: string
  task_count: number
  done_count: number
  running_count: number
  runnable_count: number
  tasks: RecomputeTask[]
}

export type FrontierView = {
  ok: boolean
  batch_id: number | null
  frontier: (RecomputeTask & { batch_id: number })[]
  waiting: (RecomputeTask & { batch_id: number })[]
  running: (RecomputeTask & { batch_id: number })[]
  done: (RecomputeTask & { batch_id: number })[]
  runnable_count: number
  waiting_count: number
  late_arrivals: { node_id: string; node_name: string; partition: string }[]
}

export type LineageNodeOption = {
  node_id: string
  node_name: string
  node_type: string
  owner: string
}

export type ActionResponse = {
  ok: boolean
  message: string
  batch?: ChangeBatch
  frontier?: FrontierView
  reused?: boolean
}

export type BatchListResponse = {
  ok: boolean
  items: ChangeBatch[]
  total: number
  frontier: FrontierView
}

export type ScheduleDetail = {
  ok: boolean
  message?: string
  batch: ChangeBatch
  runnable_tables: RecomputeTask[]
  waiting_tables: RecomputeTask[]
  running_tables: RecomputeTask[]
  completed_tables: RecomputeTask[]
  late_arrivals: { node_id: string; node_name: string; partition: string }[]
}

const BASE = '/api/lineage/recompute'

export async function fetchLineageNodes(): Promise<LineageNodeOption[]> {
  const payload = await fetchJson<{ ok: boolean; items: LineageNodeOption[] }>(`${BASE}/nodes`)
  return payload.items
}

export async function fetchBatches(): Promise<BatchListResponse> {
  return fetchJson<BatchListResponse>(`${BASE}/batches`)
}

export async function fetchBatchDetail(batchId: number): Promise<{
  ok: boolean
  message?: string
  batch: ChangeBatch
  frontier: FrontierView
  late_arrivals: { node_id: string; node_name: string; partition: string }[]
}> {
  return fetchJson(`${BASE}/batches/${batchId}`)
}

export async function fetchScheduleDetail(batchId: number): Promise<ScheduleDetail> {
  return fetchJson<ScheduleDetail>(`${BASE}/batches/${batchId}/schedule`)
}

export async function submitChangeBatch(input: {
  node_id: string
  partitions: string[]
  reason: string
}): Promise<ActionResponse> {
  const response = await request(`${BASE}/batches`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return await response.json()
}

export async function startTask(
  batchId: number,
  nodeId: string,
  partition: string,
): Promise<ActionResponse> {
  const response = await request(`${BASE}/batches/${batchId}/start`, {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, partition }),
  })
  return await response.json()
}

export async function completeTask(
  batchId: number,
  nodeId: string,
  partition: string,
): Promise<ActionResponse> {
  const response = await request(`${BASE}/batches/${batchId}/complete`, {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, partition }),
  })
  return await response.json()
}

export async function deliverPartition(
  nodeId: string,
  partition: string,
): Promise<ActionResponse> {
  const response = await request(`${BASE}/partitions/deliver`, {
    method: 'POST',
    body: JSON.stringify({ node_id: nodeId, partition }),
  })
  return await response.json()
}
