"""复算编排接口：变更批登记、复算前沿视图、调度详情与分区送达。

数据流：数据血缘（下游路径）→ 复算节点数据集 → 查询调度（逐表执行编排）。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.data_lineage import DataLineageService
from app.services.query_scheduler import QuerySchedulerService
from app.services.recompute import recompute_manager
from app.store import store

router = APIRouter(prefix="/api/lineage/recompute", tags=["复算编排"])


class ChangeBatchPayload(BaseModel):
    node_id: str
    partitions: list[str] = Field(default_factory=list)
    reason: str = ""


class TaskActionPayload(BaseModel):
    node_id: str
    partition: str


class DeliverPayload(BaseModel):
    node_id: str
    partition: str


def _lineage_service() -> DataLineageService:
    return DataLineageService()


def _evaluated_graph():
    """构建血缘图并刷新复算账本的就绪态。"""
    service = _lineage_service()
    graph = service.build_graph_from_store()
    recompute_manager.evaluate(graph)
    return service, graph


@router.post("/batches")
def submit_change_batch(payload: ChangeBatchPayload) -> dict[str, Any]:
    """从血缘图选择变更表，提交变更批并派生复算节点数据集。"""
    service, graph = _evaluated_graph()
    batch, message, reused = recompute_manager.submit_change(
        graph=graph,
        lineage_rows=store.rows(service.MODULE),
        source_node_id=payload.node_id,
        partitions=payload.partitions,
        reason=payload.reason,
    )
    if batch is None:
        return {"ok": False, "message": message}
    # 派生后再次评估，确保晚到分区登记与就绪态完整。
    recompute_manager.evaluate(graph)
    return {
        "ok": True,
        "message": message,
        "reused": reused,
        "batch": batch.to_dict(),
        "frontier": recompute_manager.frontier(batch.id),
    }


@router.get("/batches")
def list_change_batches() -> dict[str, Any]:
    """复算前沿视图入口：列出全部变更批及其复算节点数据集。"""
    _evaluated_graph()
    batches = recompute_manager.list_batches()
    return {
        "ok": True,
        "items": batches,
        "total": len(batches),
        "frontier": recompute_manager.frontier(),
    }


@router.get("/batches/{batch_id}")
def get_change_batch(batch_id: int) -> dict[str, Any]:
    """调度详情页：逐表列出可执行项与欠缺的上游分区。"""
    _evaluated_graph()
    batch = recompute_manager.get_batch(batch_id)
    if batch is None:
        return {"ok": False, "message": f"变更批 {batch_id} 不存在"}
    detail = batch.to_dict()
    # 按血缘层级（路径深度）排序，方便逐表调度。
    detail["tasks"].sort(key=lambda item: (len(item["lineage_path"]), item["node_id"]))
    return {
        "ok": True,
        "batch": detail,
        "frontier": recompute_manager.frontier(batch_id),
        "late_arrivals": recompute_manager.late_arrivals(),
    }


@router.get("/frontier")
def recompute_frontier(batch_id: int | None = None) -> dict[str, Any]:
    """复算前沿：可执行项、等待项（含欠缺的上游分区）、执行中与已完成。"""
    _evaluated_graph()
    return recompute_manager.frontier(batch_id)


@router.get("/batches/{batch_id}/schedule")
def schedule_detail(batch_id: int) -> dict[str, Any]:
    """调度详情页：排程接收复算节点数据集，逐表列出可执行项与欠缺的上游分区。"""
    _evaluated_graph()
    return QuerySchedulerService().schedule_recompute_batch(batch_id)


@router.post("/batches/{batch_id}/start")
def start_recompute(batch_id: int, payload: TaskActionPayload) -> dict[str, Any]:
    """排程开跑：仅当全部上游分区就绪（前沿项）才允许启动。"""
    _evaluated_graph()
    task, message = recompute_manager.start_task(batch_id, payload.node_id, payload.partition)
    if task is None:
        return {"ok": False, "message": message}
    batch = recompute_manager.get_batch(batch_id)
    return {"ok": True, "message": message, "task": task.to_dict(),
            "batch": batch.to_dict() if batch else None}


@router.post("/batches/{batch_id}/complete")
def complete_recompute(batch_id: int, payload: TaskActionPayload) -> dict[str, Any]:
    """登记复算产出：分区可读，级联解锁下游。"""
    _evaluated_graph()
    task, message = recompute_manager.complete_task(batch_id, payload.node_id, payload.partition)
    if task is None:
        return {"ok": False, "message": message}
    batch = recompute_manager.get_batch(batch_id)
    return {"ok": True, "message": message, "task": task.to_dict(),
            "batch": batch.to_dict() if batch else None}


@router.post("/partitions/deliver")
def deliver_partition(payload: DeliverPayload) -> dict[str, Any]:
    """晚到分区送达：外部上游分区可读后重新评估复算前沿。"""
    _evaluated_graph()
    batch = recompute_manager.deliver_partition(payload.node_id, payload.partition)
    if batch is None:
        return {"ok": False, "message": "该分区未登记为晚到分区，无需送达"}
    return {
        "ok": True,
        "message": f"分区 {payload.partition} 已送达，复算前沿已刷新",
        "batch": batch.to_dict(),
        "frontier": recompute_manager.frontier(batch.id),
    }


@router.get("/nodes")
def lineage_node_options() -> dict[str, Any]:
    """血缘图选表：供前端选择变更表。"""
    service = _lineage_service()
    nodes = [
        {
            "node_id": str(row.get("id")),
            "node_name": str(row.get("节点名称", "")),
            "node_type": str(row.get("节点类型", "")),
            "owner": str(row.get("负责人", "")),
        }
        for row in store.rows(service.MODULE)
        if row.get("status") == "在线"
    ]
    return {"ok": True, "items": nodes, "total": len(nodes)}
