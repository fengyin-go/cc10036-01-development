"""归因模型领域服务：触点权重分配、衰减计算、多模型比较。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import compute_attribution


class AttributionModelService(BaseModuleService):
    MODULE = "attribution_model"
    ENTITY = "归因配置"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["模型名称", "归因对象", "归因窗口", "触点权重", "衰减方式", "首次归因", "末次归因"]
    REQUIRED_FIELDS = ["模型名称", "归因对象", "归因窗口"]
    STATUS_ORDER = ["草稿", "计算中", "已生效", "已过期"]
    ACTION_RULES = {"开始计算": "计算中", "生效模型": "已生效", "标记过期": "已过期"}
    NEGATIVE_ACTIONS = []

    # ---- 业务方法 ----

    def compute_attribution_weights(
        self, model_id: int, touchpoints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """计算归因权重分配。"""
        model = store.find(self.MODULE, model_id)
        if model is None:
            return {"ok": False, "message": f"归因模型 {model_id} 不存在"}

        decay_method = str(model.get("衰减方式", "linear")).lower()
        model_type = "time_decay" if "decay" in decay_method else "linear"

        # 如果配置了首次/末次归因偏向，用position_based
        first_attr = str(model.get("首次归因", ""))
        last_attr = str(model.get("末次归因", ""))
        if first_attr and last_attr:
            model_type = "position_based"

        result = compute_attribution(touchpoints, model_type)

        self.run_action(model_id, "生效模型")

        return {
            "ok": True,
            "model_name": str(model.get("モデル名称", model.get("模型名称", ""))),
            "model_type": model_type,
            "attribution_window": model.get("归因窗口"),
            "touchpoints": result.touchpoints,
            "weights": [round(w, 4) for w in result.weights],
            "top_channel": result.touchpoints[result.weights.index(max(result.weights))] if result.weights else "",
            "top_weight": round(max(result.weights), 4) if result.weights else 0,
        }

    def compare_models(
        self, model_ids: list[int], touchpoints: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """比较多个归因模型的权重分配差异。"""
        comparisons: list[dict[str, Any]] = []
        for mid in model_ids:
            r = self.compute_attribution_weights(mid, touchpoints)
            if r.get("ok"):
                comparisons.append({
                    "model_name": r.get("model_name"),
                    "model_type": r.get("model_type"),
                    "weights": r.get("weights"),
                })
        # 计算各模型权重差异
        diff_metrics: dict[str, Any] = {}
        if len(comparisons) >= 2:
            diffs: list[float] = []
            for i in range(len(comparisons[0]["weights"])):
                values = [c["weights"][i] for c in comparisons if c.get("weights")]
                diffs.append(max(values) - min(values))
            diff_metrics = {
                "max_difference": round(max(diffs), 4) if diffs else 0,
                "avg_difference": round(sum(diffs) / len(diffs), 4) if diffs else 0,
            }

        return {
            "ok": True,
            "comparisons": comparisons,
            "touchpoint_count": len(touchpoints),
            "cross_model_diff": diff_metrics,
        }

    def get_active_models(self) -> list[dict[str, Any]]:
        """获取已生效的归因模型（供分群分析消费）。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "已生效"
        ]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "归因模型数据集"
        base["active_models"] = sum(1 for row in store.rows(self.MODULE) if row.get("status") == "已生效")
        return base