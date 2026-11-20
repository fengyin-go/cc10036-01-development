"""复算领域：变更批、复算节点数据集与分区就绪账本。

业务规则：
- 从血缘图选取变更表后登记一个变更批，沿下游血缘路径派生出复算节点数据集，
  每个派生表对应一条复算任务，记录其等待的分区与血缘路径。
- 分区账本记录各血缘节点在某分区上的可用性；复算任务只有在全部上游分区
  都已就绪时才允许开跑（复算前沿），缺任何上游分区都要显式列出。
- 同次复算（同一变更批的同一节点+分区）只保留一条任务，并发/重复提交去重；
  同批订单改动沿多条路径汇聚到同一派生表（如经营汇总）时只计一项。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.analytics_engine import LineageGraph

# 复算任务状态：等待分区 → 可执行（前沿） → 执行中 → 已完成
TASK_WAITING = "等待分区"
TASK_RUNNABLE = "可执行"
TASK_RUNNING = "执行中"
TASK_DONE = "已完成"

BATCH_OPEN = "进行中"
BATCH_DONE = "已完成"


@dataclass
class RecomputeTask:
    """复算节点数据集中的一条：某个派生表等待的一个分区。"""

    node_id: str
    node_name: str
    node_type: str
    partition: str
    lineage_path: list[str]          # 变更表 → … → 该节点 的血缘路径（节点名）
    missing_upstream: list[dict[str, str]] = field(default_factory=list)
    state: str = TASK_WAITING

    @property
    def key(self) -> str:
        return f"{self.node_id}@{self.partition}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "partition": self.partition,
            "lineage_path": list(self.lineage_path),
            "missing_upstream": [dict(item) for item in self.missing_upstream],
            "state": self.state,
            "ready": self.state == TASK_RUNNABLE,
        }


@dataclass
class RecomputeBatch:
    """一次变更批：一次订单/源表改动引发的整轮复算。"""

    id: int
    source_node_id: str
    source_node_name: str
    partitions: list[str]
    reason: str
    tasks: dict[str, RecomputeTask] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        tasks = list(self.tasks.values())
        done = sum(1 for task in tasks if task.state == TASK_DONE)
        running = sum(1 for task in tasks if task.state == TASK_RUNNING)
        runnable = sum(1 for task in tasks if task.state == TASK_RUNNABLE)
        return {
            "id": self.id,
            "source_node_id": self.source_node_id,
            "source_node_name": self.source_node_name,
            "partitions": list(self.partitions),
            "reason": self.reason,
            "created_at": self.created_at,
            "status": BATCH_DONE if tasks and done == len(tasks) else BATCH_OPEN,
            "task_count": len(tasks),
            "done_count": done,
            "running_count": running,
            "runnable_count": runnable,
            "tasks": [task.to_dict() for task in tasks],
        }


class RecomputeManager:
    """内存复算账本：变更批 + 分区可用性，全部基于血缘图派生。"""

    def __init__(self) -> None:
        self._batches: dict[int, RecomputeBatch] = {}
        self._seq = 0
        # 分区账本：{node_id: set(partition)}，表示该节点该分区已可读
        self._partitions: dict[str, set[str]] = {}
        # 晚到分区登记：标记为外部源、暂不可用，等待「送达」
        # {node_id: {partition: node_name}}
        self._late_arrivals: dict[str, dict[str, str]] = {}
        self._graph: LineageGraph | None = None

    # ---- 分区账本 ----

    def mark_partition(self, node_id: str, partition: str) -> None:
        self._partitions.setdefault(node_id, set()).add(partition)
        late = self._late_arrivals.get(node_id)
        if late and partition in late:
            del late[partition]

    def is_partition_available(self, node_id: str, partition: str) -> bool:
        return partition in self._partitions.get(node_id, set())

    def register_late_arrival(self, node_id: str, partition: str, node_name: str) -> None:
        if not self.is_partition_available(node_id, partition):
            self._late_arrivals.setdefault(node_id, {})[partition] = node_name

    def late_arrivals(self) -> list[dict[str, str]]:
        return [
            {"node_id": node_id, "node_name": name, "partition": partition}
            for node_id, waiting in self._late_arrivals.items()
            for partition, name in waiting.items()
        ]

    def deliver_partition(self, node_id: str, partition: str) -> RecomputeBatch | None:
        """外部晚到分区送达：登记可读并刷新所有受影响任务的就绪态。"""
        if not self._late_arrivals.get(node_id, {}).get(partition):
            return None
        self.mark_partition(node_id, partition)
        if self._graph is not None:
            self.evaluate(self._graph)
        return self.find_batch_by_partition(partition)

    def find_batch_by_partition(self, partition: str) -> RecomputeBatch | None:
        for batch in self._batches.values():
            if partition in batch.partitions:
                return batch
        return None

    # ---- 变更批登记 ----

    def submit_change(
        self,
        graph: LineageGraph,
        lineage_rows: list[dict[str, Any]],
        source_node_id: str,
        partitions: list[str],
        reason: str,
    ) -> tuple[RecomputeBatch | None, str, bool]:
        """登记变更批并派生复算节点数据集。

        返回 (批次, 消息, 是否复用既有批次)。同节点+同分区的未完成批次直接复用，
        保证同次复算只产生一项任务记录。
        """
        source = graph.nodes.get(str(source_node_id))
        if source is None:
            return None, "血缘节点不在线或不存在", False
        partitions = [p.strip() for p in partitions if p.strip()]
        if not partitions:
            return None, "必须指定至少一个复算分区", False

        # 幂等：同一变更表+同一分区集合的进行中批次直接返回，不重复派生。
        for batch in self._batches.values():
            if (
                batch.source_node_id == str(source_node_id)
                and batch.partitions == partitions
                and batch.to_dict()["status"] == BATCH_OPEN
            ):
                return batch, "同次复算已在进行，复用既有变更批，未重复生成任务", True

        self._seq += 1
        batch = RecomputeBatch(
            id=self._seq,
            source_node_id=str(source_node_id),
            source_node_name=source.node_name,
            partitions=list(partitions),
            reason=reason or "源表数据变更",
            created_at=date.today().isoformat(),
        )

        name_map = {str(row.get("id")): str(row.get("节点名称", "")) for row in lineage_rows}
        # 变更表自身分区视为已就绪（本批改动就是它产出的）。
        for partition in partitions:
            self.mark_partition(str(source_node_id), partition)

        # 下游血缘路径：沿每条路径为派生表生成复算任务。
        paths = graph.downstream_chain(str(source_node_id))
        for path in paths:
            path_names = [name_map.get(nid, nid) for nid in path]
            for node_id in path[1:]:  # 跳过变更表自身
                node = graph.nodes.get(node_id)
                if node is None:
                    continue
                for partition in partitions:
                    task = RecomputeTask(
                        node_id=node_id,
                        node_name=node.node_name,
                        node_type=node.node_type,
                        partition=partition,
                        lineage_path=list(path_names),
                    )
                    # 同一节点+分区只保留一条（多条路径汇聚时合并，如经营汇总）。
                    batch.tasks.setdefault(task.key, task)

        self._graph = graph
        for task in batch.tasks.values():
            self._refresh_task(batch, task)
        self._batches[batch.id] = batch
        return batch, f"变更批已提交，沿 {len(paths)} 条血缘路径派生 {len(batch.tasks)} 项复算任务", False

    # ---- 就绪评估（复算前沿） ----

    def _refresh_task(self, batch: RecomputeBatch, task: RecomputeTask) -> None:
        """根据上游分区账本重算任务状态；已完成/执行中的任务不回退。"""
        if task.state in (TASK_RUNNING, TASK_DONE) or self._graph is None:
            return
        partition = task.partition
        missing: list[dict[str, str]] = []
        node = self._graph.nodes.get(task.node_id)
        if node is not None:
            for up_id in node.upstream_ids:
                if not self.is_partition_available(up_id, partition):
                    up_node = self._graph.nodes.get(up_id)
                    missing.append({
                        "node_id": up_id,
                        "node_name": up_node.node_name if up_node else up_id,
                        "partition": partition,
                    })
                    # 无上游的外部源头分区缺失 → 登记为晚到，等待送达。
                    if up_node is not None and not up_node.upstream_ids:
                        self.register_late_arrival(up_id, partition, up_node.node_name)
        task.missing_upstream = missing
        if self.is_partition_available(task.node_id, partition):
            task.state = TASK_DONE
        elif missing:
            task.state = TASK_WAITING
        else:
            task.state = TASK_RUNNABLE

    def evaluate(self, graph: LineageGraph) -> None:
        """刷新全部进行中批次的任务就绪态。"""
        self._graph = graph
        for batch in self._batches.values():
            for task in batch.tasks.values():
                self._refresh_task(batch, task)

    # ---- 执行动作 ----

    def start_task(self, batch_id: int, node_id: str, partition: str) -> tuple[RecomputeTask | None, str]:
        batch = self._batches.get(batch_id)
        if batch is None:
            return None, f"变更批 {batch_id} 不存在"
        task = batch.tasks.get(f"{node_id}@{partition}")
        if task is None:
            return None, "该复算项不属于此变更批"
        if task.state == TASK_DONE:
            return None, "该分区已复算完成，请勿重复提交"
        if task.state == TASK_RUNNING:
            return None, "该复算项正在执行中，同次复算只计一项"
        if task.state == TASK_WAITING:
            names = "、".join(item["node_name"] for item in task.missing_upstream)
            return None, f"上游分区未齐（欠缺：{names}），不得提前开跑"
        task.state = TASK_RUNNING
        return task, f"{task.node_name} 分区 {partition} 已开始复算"

    def complete_task(self, batch_id: int, node_id: str, partition: str) -> tuple[RecomputeTask | None, str]:
        batch = self._batches.get(batch_id)
        if batch is None:
            return None, f"变更批 {batch_id} 不存在"
        task = batch.tasks.get(f"{node_id}@{partition}")
        if task is None:
            return None, "该复算项不属于此变更批"
        if task.state != TASK_RUNNING:
            return None, "只有执行中的复算项可以登记完成"
        task.state = TASK_DONE
        # 复算产出：该节点分区进入可读账本，并级联刷新下游。
        self.mark_partition(task.node_id, partition)
        if self._graph is not None:
            for other in batch.tasks.values():
                if other.state in (TASK_WAITING, TASK_RUNNABLE):
                    self._refresh_task(batch, other)
        return task, f"{task.node_name} 分区 {partition} 复算完成并可读取"

    # ---- 查询视图 ----

    def list_batches(self) -> list[dict[str, Any]]:
        return [batch.to_dict() for batch in sorted(self._batches.values(), key=lambda b: b.id, reverse=True)]

    def get_batch(self, batch_id: int) -> RecomputeBatch | None:
        return self._batches.get(batch_id)

    def frontier(self, batch_id: int | None = None) -> dict[str, Any]:
        """复算前沿视图：按派生表列出等待分区、可执行项与欠缺的上游分区。"""
        batches = [self._batches[batch_id]] if batch_id in self._batches else list(self._batches.values())
        runnable_items: list[dict[str, Any]] = []
        waiting_items: list[dict[str, Any]] = []
        running_items: list[dict[str, Any]] = []
        done_items: list[dict[str, Any]] = []
        for batch in batches:
            for task in batch.tasks.values():
                item = {"batch_id": batch.id, **task.to_dict()}
                if task.state == TASK_RUNNABLE:
                    runnable_items.append(item)
                elif task.state == TASK_WAITING:
                    waiting_items.append(item)
                elif task.state == TASK_RUNNING:
                    running_items.append(item)
                else:
                    done_items.append(item)
        return {
            "ok": True,
            "batch_id": batch_id,
            "frontier": runnable_items,
            "waiting": waiting_items,
            "running": running_items,
            "done": done_items,
            "runnable_count": len(runnable_items),
            "waiting_count": len(waiting_items),
            "late_arrivals": self.late_arrivals(),
        }


# 单例：进程内复算账本
recompute_manager = RecomputeManager()
