"""实验分析领域服务：A/B指标计算、置信度、异常检测联动。"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store
from app.analytics_engine import compute_confidence_interval, compute_ab_sample_size


class AbAnalysisService(BaseModuleService):
    MODULE = "ab_analysis"
    ENTITY = "实验配置"
    OPERATION_TERM = "计算"
    LIST_FIELDS = ["实验名称", "对照组", "实验组", "核心指标", "置信度要求", "最小样本量", "实验周期"]
    REQUIRED_FIELDS = ["实验名称", "对照组", "实验组"]
    STATUS_ORDER = ["草稿", "进行中", "已结束", "已归档"]
    ACTION_RULES = {"开始实验": "进行中", "结束实验": "已结束", "归档实验": "已归档"}
    NEGATIVE_ACTIONS = []

    # ---- 业务方法 ----

    def analyze(
        self, experiment_id: int, control_values: list[float],
        treatment_values: list[float],
    ) -> dict[str, Any]:
        """执行A/B实验分析，计算置信区间和显著性。"""
        experiment = store.find(self.MODULE, experiment_id)
        if experiment is None:
            return {"ok": False, "message": f"实验 {experiment_id} 不存在"}

        result = compute_confidence_interval(control_values, treatment_values)

        self.run_action(experiment_id, "开始实验")
        if result.get("significant"):
            self.run_action(experiment_id, "结束实验")

        return {
            "ok": True,
            "experiment_name": str(experiment.get("实验名称", "")),
            "metric": str(experiment.get("核心指标", "")),
            "control_size": len(control_values),
            "treatment_size": len(treatment_values),
            **result,
        }

    def estimate_required_sample(
        self, experiment_id: int, baseline_rate: float, min_effect: float,
    ) -> dict[str, Any]:
        """估算实验所需最小样本量。"""
        experiment = store.find(self.MODULE, experiment_id)
        if experiment is None:
            return {"ok": False, "message": f"实验 {experiment_id} 不存在"}
        required = compute_ab_sample_size(baseline_rate, min_effect)
        return {
            "ok": True,
            "experiment_name": experiment.get("实验名称"),
            "baseline_rate": baseline_rate,
            "min_detectable_effect": min_effect,
            "required_sample_size": required,
            "configured_min_sample": experiment.get("最小样本量"),
        }

    def check_anomalies_during_experiment(
        self, experiment_id: int, metric_values: list[float],
    ) -> dict[str, Any]:
        """实验期间异常检测（实验分析→异常检测跨模块消费）。"""
        from app.services import service_for
        anomaly_svc = service_for("anomaly_detect")
        if anomaly_svc is None:
            return {"ok": False, "message": "异常检测服务不可用"}
        active_rules = anomaly_svc.get_active_rules()
        if not active_rules:
            return {"ok": True, "message": "无活跃检测规则", "anomalies": []}
        rule_ids = [int(r["id"]) for r in active_rules]
        batch_result = anomaly_svc.batch_detect(rule_ids, metric_values)
        return {
            "ok": True,
            "experiment_id": experiment_id,
            "anomaly_count": batch_result.get("total_anomalies", 0),
            "details": batch_result.get("results", []),
        }

    def get_running_experiments(self) -> list[dict[str, Any]]:
        """获取进行中的实验。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("status") == "进行中"
        ]

    def domain_snapshot(self) -> dict[str, Any]:
        base = super().domain_snapshot()
        rows = store.rows(self.MODULE)
        base["artifact"] = "AB实验数据集"
        base["running_count"] = sum(1 for row in rows if row.get("status") == "进行中")
        base["completed_count"] = sum(1 for row in rows if row.get("status") == "已结束")
        return base