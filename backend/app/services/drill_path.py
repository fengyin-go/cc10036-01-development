"""下钻路径领域服务：层级分析、度量聚合、看板联动。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import compute_drill_levels


class DrillPathService(BaseModuleService):
    MODULE = "drill_path"
    ENTITY = "下钻配置"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["路径名称", "起始维度", "下钻层级", "各层度量", "是否启用手动", "关联看板", "路径说明"]
    REQUIRED_FIELDS = ["路径名称", "起始维度", "下钻层级"]
    STATUS_ORDER = ["草稿", "已启用", "已停用"]
    ACTION_RULES = {"启用路径": "已启用", "停用路径": "已停用"}
    NEGATIVE_ACTIONS = ["停用路径"]

    # ---- 业务方法 ----

    def execute_drill(
        self, path_id: int, data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """执行下钻分析：逐层聚合度量。"""
        path_config = store.find(self.MODULE, path_id)
        if path_config is None:
            return {"ok": False, "message": f"下钻配置 {path_id} 不存在"}

        hierarchy_raw = str(path_config.get("下钻层级", ""))
        hierarchy = [h.strip() for h in hierarchy_raw.split(",") if h.strip()]
        measures_raw = str(path_config.get("各层度量", ""))
        measures = [m.strip() for m in measures_raw.split(",") if m.strip()]

        levels = compute_drill_levels(data, hierarchy, measures)

        return {
            "ok": True,
            "path_name": str(path_config.get("路径名称", "")),
            "start_dimension": path_config.get("起始维度"),
            "hierarchy": hierarchy,
            "measures": measures,
            "levels": levels,
            "level_count": len(levels),
            "associated_dashboard": path_config.get("关联看板"),
        }

    def get_drill_paths_for_dashboard(self, dashboard_name: str) -> list[dict[str, Any]]:
        """获取某看板关联的下钻路径（数据范围→下钻路径消费）。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("关联看板") == dashboard_name and row.get("status") == "已启用"
        ]

    def get_enabled_paths(self) -> list[dict[str, Any]]:
        """获取所有已启用路径。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "已启用"
        ]

    def compare_drill_results(
        self, path_ids: list[int], data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """比较多条下钻路径的分析结果。"""
        results: list[dict[str, Any]] = []
        for pid in path_ids:
            r = self.execute_drill(pid, data)
            if r.get("ok"):
                results.append(r)
        return {
            "ok": True,
            "path_count": len(path_ids),
            "results": results,
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "下钻路径数据集"
        base["enabled_paths"] = sum(1 for row in store.rows(self.MODULE) if row.get("status") == "已启用")
        return base