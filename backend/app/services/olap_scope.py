"""数据范围领域服务：行级/列级范围控制、数据领域隔离。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class OlapScopeService(BaseModuleService):
    MODULE = "olap_scope"
    ENTITY = "范围规则"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["规则名称", "数据范围", "授权对象", "可见字段", "行过滤条件", "生效时间", "失效时间"]
    REQUIRED_FIELDS = ["规则名称", "数据范围", "授权对象"]
    STATUS_ORDER = ["草稿", "已生效", "已冻结", "已撤销"]
    ACTION_RULES = {"生效规则": "已生效", "冻结规则": "已冻结", "撤销规则": "已撤销"}
    NEGATIVE_ACTIONS = ["撤销规则"]

    # ---- 业务方法 ----

    def apply_scope_filters(
        self, rule_ids: list[int], data: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """对数据应用多条范围规则的并集过滤。"""
        visible_columns: set[str] = set()
        row_filters: list[str] = []
        matched_rules: list[str] = []

        for rid in rule_ids:
            rule = store.find(self.MODULE, rid)
            if rule is None or rule.get("status") != "已生效":
                continue
            matched_rules.append(str(rule.get("规则名称", "")))
            cols = str(rule.get("可见字段", "")).split(",")
            for c in cols:
                c = c.strip()
                if c:
                    visible_columns.add(c)
            rf = str(rule.get("行过滤条件", "")).strip()
            if rf:
                row_filters.append(rf)

        # 应用列过滤
        if visible_columns:
            filtered_data = [
                {k: v for k, v in row.items() if k in visible_columns}
                for row in data
            ]
        else:
            filtered_data = list(data)

        # 应用行过滤
        if row_filters:
            for rf in row_filters:
                filtered_data = _apply_row_filter(filtered_data, rf)

        return {
            "ok": True,
            "applied_rules": matched_rules,
            "rule_count": len(matched_rules),
            "original_rows": len(data),
            "filtered_rows": len(filtered_data),
            "visible_columns": sorted(visible_columns),
            "sample": filtered_data[:5],
        }

    def check_access(
        self, principal: str, data_source: str,
    ) -> dict[str, Any]:
        """检查主体对数据源的访问范围。"""
        rows = store.rows(self.MODULE)
        applicable: list[dict[str, Any]] = []
        for row in rows:
            if row.get("status") != "已生效":
                continue
            auth_obj = str(row.get("授权对象", ""))
            data_range = str(row.get("数据范围", ""))
            if principal in auth_obj.split(",") and data_source in data_range:
                applicable.append({
                    "rule_name": row.get("规则名称"),
                    "visible_fields": str(row.get("可见字段", "")).split(","),
                    "row_filter": row.get("行过滤条件"),
                })
        return {
            "ok": True,
            "principal": principal,
            "data_source": data_source,
            "has_access": len(applicable) > 0,
            "applicable_rules": applicable,
        }

    def get_effective_scopes(self) -> list[dict[str, Any]]:
        """获取所有生效的数据范围规则（供语义层消费）。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "已生效"
        ]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        base["artifact"] = "数据范围规则数据集"
        base["effective_rules"] = sum(1 for row in store.rows(self.MODULE) if row.get("status") == "已生效")
        return base


def _apply_row_filter(
    data: list[dict[str, Any]], filter_expr: str,
) -> list[dict[str, Any]]:
    """应用行级过滤表达式。"""
    results: list[dict[str, Any]] = []
    for row in data:
        try:
            row_context = {**row}
            if eval(filter_expr, {"__builtins__": {}}, row_context):
                results.append(row)
        except Exception:
            results.append(row)
    return results