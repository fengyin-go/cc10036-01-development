"""查询调度领域服务：任务编排、依赖链、超时控制。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class QuerySchedulerService(BaseModuleService):
    MODULE = "query_scheduler"
    ENTITY = "调度计划"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["计划名称", "查询语句", "执行周期", "依赖任务", "超时分钟", "失败重试", "优先级"]
    REQUIRED_FIELDS = ["计划名称", "查询语句", "执行周期"]
    STATUS_ORDER = ["待调度", "执行中", "已完成", "调度失败", "已暂停"]
    ACTION_RULES = {"开始执行": "执行中", "完成调度": "已完成", "标记失败": "调度失败", "暂停计划": "已暂停"}
    NEGATIVE_ACTIONS = ["标记失败"]

    # ---- 业务方法 ----

    def build_dependency_graph(self) -> dict[str, Any]:
        """构建调度计划的依赖图（数据血缘→查询调度消费）。"""
        rows = store.rows(self.MODULE)
        graph: dict[str, list[str]] = {}  # plan_name -> [dependent_plan_names]
        for row in rows:
            name = str(row.get("计划名称", ""))
            deps_raw = str(row.get("依赖任务", ""))
            deps = [d.strip() for d in deps_raw.split(",") if d.strip()]
            graph[name] = deps
        return {"ok": True, "nodes": len(rows), "graph": graph}

    def topological_order(self) -> dict[str, Any]:
        """按依赖拓扑排序调度计划（血缘关系→调度顺序）。"""
        deps = self.build_dependency_graph().get("graph", {})
        in_degree: dict[str, int] = {name: 0 for name in deps}
        for name, dep_list in deps.items():
            for dep in dep_list:
                if dep in in_degree:
                    in_degree[dep] = in_degree.get(dep, 0) + 1

        from collections import deque
        queue: deque[str] = deque(name for name, deg in in_degree.items() if deg == 0)
        order: list[str] = []
        while queue:
            node = queue.popleft()
            order.append(node)
            if node in deps:
                for dep in deps[node]:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        has_cycle = len(order) != len(deps)
        return {
            "ok": True,
            "plan_count": len(deps),
            "execution_order": order,
            "has_cycle": has_cycle,
            "cycle_nodes": [n for n, d in in_degree.items() if d > 0],
        }

    def get_ready_plans(self) -> list[dict[str, Any]]:
        """获取待调度且无依赖的计划。"""
        rows = store.rows(self.MODULE)
        ready: list[dict[str, Any]] = []
        for row in rows:
            if row.get("status") != "待调度":
                continue
            deps_raw = str(row.get("依赖任务", ""))
            if not deps_raw.strip():
                ready.append(row)
                continue
            dep_names = [d.strip() for d in deps_raw.split(",")]
            all_completed = all(
                _is_completed(r) for r in rows
                if str(r.get("计划名称", "")) in dep_names
            )
            if all_completed:
                ready.append(row)
        return ready

    def retry_failed(self) -> dict[str, Any]:
        """重试失败的调度计划。"""
        rows = store.rows(self.MODULE)
        retried = 0
        for row in rows:
            if row.get("status") == "调度失败":
                max_retries = _parse_int(row.get("失败重试"), 3)
                retry_count = row.get("_retry_count", 0)
                if retry_count < max_retries:
                    row["_retry_count"] = retry_count + 1
                    self.run_action(int(row["id"]), "开始执行")
                    retried += 1
        return {"ok": True, "retried_count": retried}

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "查询调度数据集"
        base["ready_count"] = len(self.get_ready_plans())
        return base


def _is_completed(row: dict[str, Any]) -> bool:
    return row.get("status") == "已完成"


def _parse_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default