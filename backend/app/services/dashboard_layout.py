"""看板布局领域服务：看板配置、布局管理、数据消费。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DashboardLayoutService(BaseModuleService):
    MODULE = "dashboard_layout"
    ENTITY = "看板配置"
    OPERATION_TERM = "聚合"
    LIST_FIELDS = ["看板名称", "所属业务域", "图表布局", "数据刷新间隔", "是否公开", "创建人", "上次修改"]
    REQUIRED_FIELDS = ["看板名称", "所属业务域", "图表布局"]
    STATUS_ORDER = ["草稿", "已发布", "已下线"]
    ACTION_RULES = {"发布看板": "已发布", "下线看板": "已下线"}
    NEGATIVE_ACTIONS = ["下线看板"]

    # ---- 业务方法 ----

    def get_published_dashboards(self) -> list[dict[str, Any]]:
        """获取所有已发布看板（供报表订阅和导出消费）。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "已发布"
        ]

    def parse_layout(self, dashboard_id: int) -> dict[str, Any]:
        """解析看板布局配置，拆分为独立的图表卡片。"""
        dashboard = store.find(self.MODULE, dashboard_id)
        if dashboard is None:
            return {"ok": False, "message": f"看板 {dashboard_id} 不存在"}
        layout_raw = str(dashboard.get("图表布局", ""))
        # 格式: type:title:w:h:x:y;type:title:w:h:x:y
        cards: list[dict[str, Any]] = []
        for card_str in layout_raw.split(";"):
            parts = card_str.strip().split(":")
            if len(parts) >= 2:
                cards.append({
                    "type": parts[0].strip(),
                    "title": parts[1].strip(),
                    "width": int(parts[2]) if len(parts) > 2 else 1,
                    "height": int(parts[3]) if len(parts) > 3 else 1,
                    "x": int(parts[4]) if len(parts) > 4 else 0,
                    "y": int(parts[5]) if len(parts) > 5 else 0,
                })
        return {
            "ok": True,
            "dashboard_name": str(dashboard.get("看板名称", "")),
            "domain": str(dashboard.get("所属业务域", "")),
            "refresh_interval": dashboard.get("数据刷新间隔"),
            "cards": cards,
            "card_count": len(cards),
        }

    def get_dashboards_by_domain(self, domain: str) -> list[dict[str, Any]]:
        """获取某业务域下所有看板。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("所属业务域") == domain
        ]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        rows = store.rows(self.MODULE)
        base["artifact"] = "看板布局数据集"
        base["published_count"] = sum(1 for row in rows if row.get("status") == "已发布")
        base["public_count"] = sum(1 for row in rows if row.get("是否公开") == "是")
        return base