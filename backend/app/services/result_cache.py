"""结果缓存领域服务：缓存生命周期管理、命中率追踪、TTL控制。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import CacheManager

# 全局缓存管理器，多模块共享
_global_cache = CacheManager(max_entries=500, max_memory_bytes=200 * 1024 * 1024)


class ResultCacheService(BaseModuleService):
    MODULE = "result_cache"
    ENTITY = "缓存条目"
    OPERATION_TERM = "存储"
    LIST_FIELDS = ["缓存键", "查询描述", "结果行数", "字节大小", "创建时间", "TTL秒", "命中次数"]
    REQUIRED_FIELDS = ["缓存键", "查询描述", "结果行数"]
    STATUS_ORDER = ["有效", "已失效", "已清理"]
    ACTION_RULES = {"标记失效": "已失效", "清理缓存": "已清理"}
    NEGATIVE_ACTIONS = ["清理缓存"]

    # ---- 业务方法 ----

    def get_or_compute(
        self, query_desc: str, params: dict[str, Any],
        compute_fn: Any, ttl_seconds: int = 300,
    ) -> dict[str, Any]:
        """缓存读取或计算（供切片查询和报表消费）。"""
        key = _global_cache.compute_key(query_desc, params)
        cached = _global_cache.get(key)
        if cached is not None:
            return {"ok": True, "from_cache": True, "data": cached, "cache_key": key}
        result = compute_fn()
        _global_cache.put(key, result, ttl_seconds=ttl_seconds)
        return {"ok": True, "from_cache": False, "data": result, "cache_key": key}

    def invalidate_cache(self, cache_key: str) -> dict[str, Any]:
        """标记缓存失效。"""
        success = _global_cache.invalidate(cache_key)
        if success:
            self.run_action(1, "标记失效")
        return {"ok": success, "cache_key": cache_key}

    def cache_stats(self) -> dict[str, Any]:
        """获取缓存统计（供查询加速器消费）。"""
        stats = _global_cache.stats()
        rows = store.rows(self.MODULE)
        return {
            **stats,
            "registered_entries": len(rows),
            "active_entries": sum(1 for row in rows if row.get("status") == "有效"),
        }

    def cleanup_expired(self) -> dict[str, Any]:
        """清理过期缓存条目。"""
        rows = store.rows(self.MODULE)
        cleaned = 0
        for row in list(rows):
            if row.get("status") == "已失效":
                rows.remove(row)
                cleaned += 1
        return {"ok": True, "cleaned_entries": cleaned, "remaining": len(rows)}

    def compute_cache_turnover(self) -> dict[str, Any]:
        """计算缓存周转指标。"""
        stats = _global_cache.stats()
        return {
            "ok": True,
            "hit_rate": round(
                stats["total_hits"] / max(stats["total_hits"] + stats["expired"], 1) * 100, 2,
            ),
            "active_ratio": round(
                stats["active"] / max(stats["total"], 1) * 100, 2,
            ),
            "memory_mb": round(stats["memory_bytes"] / (1024 * 1024), 2),
        }

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        stats = _global_cache.stats()
        base["artifact"] = "结果缓存数据集"
        base["cache_hit_count"] = stats["total_hits"]
        base["aggregate_hit_rate"] = round(
            stats["total_hits"] / max(stats["total_hits"] + stats["expired"], 1) * 100, 2
        )
        return base