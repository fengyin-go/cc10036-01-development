"""语义层领域服务：物理表→业务语义映射，屏蔽底层Schema变更。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class SemanticLayerService(BaseModuleService):
    MODULE = "semantic_layer"
    ENTITY = "语义定义"
    OPERATION_TERM = "关联"
    LIST_FIELDS = ["语义名称", "物理表", "字段映射", "关联关系", "过滤条件", "安全规则", "描述说明"]
    REQUIRED_FIELDS = ["语义名称", "物理表", "字段映射"]
    STATUS_ORDER = ["草稿", "已验证", "已发布", "已废弃"]
    ACTION_RULES = {"验证语义": "已验证", "发布语义": "已发布", "废弃语义": "已废弃"}
    NEGATIVE_ACTIONS = ["废弃语义"]

    # ---- 业务方法 ----

    def map_metric_to_physical(self, metric_code: str) -> dict[str, Any] | None:
        """将指标映射到物理表和字段（为立方构建提供物理元数据）。"""
        from app.services import service_for
        metric_svc = service_for("metric_def")
        if metric_svc is None:
            return None
        caliber_info = metric_svc.resolve_metric_caliber(metric_code)
        if caliber_info is None:
            return None
        # 在语义层定义中查找对应映射
        rows = store.rows(self.MODULE)
        for semantic_def in rows:
            if semantic_def.get("status") != "已发布":
                continue
            field_mapping = str(semantic_def.get("字段映射", ""))
            if caliber_info["name"] in field_mapping or caliber_info["code"] in field_mapping:
                return {
                    "metric_code": metric_code,
                    "metric_name": caliber_info["name"],
                    "physical_table": semantic_def.get("物理表"),
                    "field_mapping": field_mapping,
                    "relations": semantic_def.get("关联关系"),
                    "filters": semantic_def.get("过滤条件"),
                    "security": semantic_def.get("安全规则"),
                    "aggregator": caliber_info["aggregator"],
                }
        return None

    def get_dimension_mapping(self, dimension_name: str) -> dict[str, Any] | None:
        """获取维度的语义映射。"""
        rows = store.rows(self.MODULE)
        for semantic_def in rows:
            if semantic_def.get("status") != "已发布":
                continue
            field_mapping = str(semantic_def.get("字段映射", ""))
            if dimension_name in field_mapping:
                return {
                    "dimension": dimension_name,
                    "physical_table": semantic_def.get("物理表"),
                    "physical_column": field_mapping.split(dimension_name)[0].rstrip(":") if ":" in field_mapping else field_mapping,
                    "security_rules": semantic_def.get("安全规则"),
                }
        return None

    def query_physical_tables_for_cube(self, cube_measures: list[str]) -> list[dict[str, Any]]:
        """为立方构建提供所需的物理表集。"""
        tables_set: dict[str, dict[str, Any]] = {}
        rows = store.rows(self.MODULE)
        for semantic_def in rows:
            if semantic_def.get("status") != "已发布":
                continue
            table = str(semantic_def.get("物理表", ""))
            field_map = str(semantic_def.get("字段映射", ""))
            if any(m.lower() in field_map.lower() for m in cube_measures):
                if table not in tables_set:
                    tables_set[table] = {
                        "table": table,
                        "fields": field_map,
                        "relations": semantic_def.get("关联关系"),
                        "security": semantic_def.get("安全规则"),
                    }
        return list(tables_set.values())

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "语义映射数据集"
        published_count = sum(
            1 for row in store.rows(self.MODULE) if row.get("status") == "已发布"
        )
        base["published_count"] = published_count
        return base