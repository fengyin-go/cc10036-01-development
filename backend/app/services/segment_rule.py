"""分群圈选领域服务：条件解析、人群计算、结果生成。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import parse_segment_conditions, segment_population


class SegmentRuleService(BaseModuleService):
    MODULE = "segment_rule"
    ENTITY = "分群规则"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["分群名称", "人群类型", "筛选条件", "排除条件", "交集策略", "刷新周期", "分群规模"]
    REQUIRED_FIELDS = ["分群名称", "人群类型", "筛选条件"]
    STATUS_ORDER = ["草稿", "计算中", "已生效", "已过期"]
    ACTION_RULES = {"开始计算": "计算中", "生效分群": "已生效", "标记过期": "已过期"}
    NEGATIVE_ACTIONS = ["标记过期"]

    # ---- 业务方法 ----

    def compute_segment(
        self, rule_id: int, population: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """执行分群计算：解析条件并从人群中圈选出目标群体。"""
        rule = store.find(self.MODULE, rule_id)
        if rule is None:
            return {"ok": False, "message": f"分群规则 {rule_id} 不存在"}

        include_expr = str(rule.get("筛选条件", ""))
        exclude_expr = str(rule.get("排除条件", ""))
        intersect_strategy = str(rule.get("交集策略", "all"))

        include_conditions = parse_segment_conditions(include_expr)
        exclude_conditions = parse_segment_conditions(exclude_expr)

        matched, count = segment_population(
            population, include_conditions, exclude_conditions, intersect_strategy,
        )

        # 更新分群规模字段
        rule["分群规模"] = str(count)
        self.run_action(rule_id, "生效分群")

        return {
            "ok": True,
            "rule_name": str(rule.get("分群名称", "")),
            "population_total": len(population),
            "matched_count": count,
            "match_rate": round(count / len(population) * 100, 2) if population else 0,
            "include_conditions": [vars(c) for c in include_conditions],
            "exclude_conditions": [vars(c) for c in exclude_conditions],
            "sample": matched[:5],
        }

    def get_active_segments(self) -> list[dict[str, Any]]:
        """获取所有已生效的分群（供同期群分析和归因模型消费）。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "已生效"
        ]

    def estimate_segment_size(self, rule_id: int, population_size: int) -> dict[str, Any]:
        """估算分群规模（抽样方法）。"""
        rule = store.find(self.MODULE, rule_id)
        if rule is None:
            return {"ok": False, "message": f"分群规则 {rule_id} 不存在"}
        # 简化估计：按条件复杂度估算
        include_conds = len(str(rule.get("筛选条件", "")).split(";"))
        exclude_conds = len(str(rule.get("排除条件", "")).split(";"))
        total_conds = include_conds + exclude_conds
        # 经验公式：每个条件约减半
        estimated = population_size * (0.6 ** max(total_conds, 1))
        return {
            "ok": True,
            "population_size": population_size,
            "condition_count": total_conds,
            "estimated_size": max(1, int(estimated)),
            "refresh_cycle": rule.get("刷新周期"),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        segments = store.rows(self.MODULE)
        base["artifact"] = "分群规则数据集"
        base["active_segments"] = sum(1 for row in segments if row.get("status") == "已生效")
        base["total_population_covered"] = sum(
            _parse_int(row.get("分群规模"), 0) for row in segments
        )
        return base


def _parse_int(val: Any, default: int) -> int:
    try:
        return int(val)
    except (ValueError, TypeError):
        return default