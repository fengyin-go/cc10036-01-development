"""查询加速领域服务：物化视图策略、预计算推荐、缓存命中率。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import recommend_materialization


class QueryAcceleratorService(BaseModuleService):
    MODULE = "query_accelerator"
    ENTITY = "加速配置"
    OPERATION_TERM = "存储"
    LIST_FIELDS = ["配置名称", "目标查询", "加速方式", "预计算范围", "刷新策略", "命中率目标", "存储预算"]
    REQUIRED_FIELDS = ["配置名称", "目标查询", "加速方式"]
    STATUS_ORDER = ["草稿", "已启用", "预热中", "已停用"]
    ACTION_RULES = {"启用加速": "已启用", "开始预热": "预热中", "停用加速": "已停用"}
    NEGATIVE_ACTIONS = ["停用加速"]

    # ---- 业务方法 ----

    def analyze_query_patterns(
        self, query_stats: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """分析查询模式并推荐物化策略（合作分析）。"""
        recommendations = recommend_materialization(query_stats)

        return {
            "ok": True,
            "query_count": len(query_stats),
            "recommendations": recommendations,
            "recommended_count": len(recommendations),
            "high_priority": [
                r for r in recommendations if r.get("priority") == "高"
            ],
        }

    def compute_cache_hit_rate(self) -> dict[str, Any]:
        """计算全局缓存命中率（结果缓存→查询加速消费）。"""
        from app.services.result_cache import _global_cache
        stats = _global_cache.stats()
        hits = stats["total_hits"]
        total = hits + stats["expired"]  # 简化：active + expired = total requests
        hit_rate = round(hits / max(total, 1) * 100, 2)
        return {
            "ok": True,
            "hit_count": hits,
            "total_requests_approx": total,
            "hit_rate_pct": hit_rate,
            "active_entries": stats["active"],
            "memory_usage_mb": round(stats["memory_bytes"] / (1024 * 1024), 2),
        }

    def warm_up_config(
        self, config_id: int, precompute_data: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """执行预热：根据配置预计算数据。"""
        config = store.find(self.MODULE, config_id)
        if config is None:
            return {"ok": False, "message": f"加速配置 {config_id} 不存在"}

        self.run_action(config_id, "启用加速")
        self.run_action(config_id, "开始预热")

        method = str(config.get("加速方式", "结果缓存"))
        precompute_range = str(config.get("预计算范围", ""))
        refresh_strategy = str(config.get("刷新策略", "手动"))
        storage_budget = str(config.get("存储预算", "1GB"))

        return {
            "ok": True,
            "config_name": str(config.get("配置名称", "")),
            "method": method,
            "precompute_range": precompute_range,
            "refresh_strategy": refresh_strategy,
            "storage_budget": storage_budget,
            "precomputed_rows": len(precompute_data) if precompute_data else 0,
            "status": "预热中",
        }

    def get_active_configs(self) -> list[dict[str, Any]]:
        """获取所有活跃的加速配置。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") in ("已启用", "预热中")
        ]

    def compare_performance(
        self, config_ids: list[int], query_time_ms: float,
    ) -> dict[str, Any]:
        """比较加速效果：估算各配置下查询耗时。"""
        results: list[dict[str, Any]] = []
        for cid in config_ids:
            config = store.find(self.MODULE, cid)
            if config is None:
                continue
            method = str(config.get("加速方式", "无"))
            # 简化加速比模型
            speedup = {
                "物化视图": 0.1,
                "预计算": 0.25,
                "结果缓存": 0.05,
                "无": 1.0,
            }.get(method, 0.5)
            estimated_ms = query_time_ms * speedup
            results.append({
                "config_id": cid,
                "config_name": config.get("配置名称"),
                "method": method,
                "estimated_query_ms": round(estimated_ms, 1),
                "speedup_ratio": round(1 / max(speedup, 0.001), 1),
            })
        return {
            "ok": True,
            "original_query_ms": query_time_ms,
            "results": sorted(results, key=lambda x: x["estimated_query_ms"]),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "查询加速配置数据集"
        base["active_configs"] = sum(
            1 for row in store.rows(self.MODULE)
            if row.get("status") in ("已启用", "预热中")
        )
        return base