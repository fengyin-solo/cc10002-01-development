"""聚合查询业务规则：状态流转、字段校验、按确认口径执行与重算。

口径版本化约定：
- 新执行/重算都采用规则当前确认后的口径版本，并把当时的计算公式快照进结果；
- 结果记录一旦生成不改动，已有结果保留当时口径及版本来源；
- 只有用户主动执行或重算才产生新的结果记录，发布切换版本不会自动重算。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.metricversion import (
    find_version,
    normalize_version,
    rule_version_state,
    version_sort_key,
)
from app.store import store

MODULE = "aggregation"
RESULT_TABLE = "aggregation_result"
METRIC_MODULE = "metricdef"
REQUIRED_FIELDS = ["规则编号", "聚合函数", "目标指标"]
STATUS_ORDER = ["草稿", "待校验", "已启用", "已停用"]
ACTION_RULES = {"提交校验": "待校验", "启用规则": "已启用", "停用规则": "已停用"}
NEGATIVE_ACTIONS = ["停用规则"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class AggregationService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("规则编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._enrich(row) for row in rows[start:start + size]], total

    @staticmethod
    def _enrich(row: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(row)
        enriched["版本状态"] = rule_version_state(row)
        return enriched

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return self._enrich(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["口径版本"] = str(values.get("口径版本") or "").strip()
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"聚合规则 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于聚合查询可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"聚合规则已{action}"

    # ---------- 执行与结果 ----------

    def list_results(
        self,
        *,
        rule_id: int | None = None,
        metric_code: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(RESULT_TABLE)
        if rule_id is not None:
            rows = [row for row in rows if int(row.get("规则id", 0)) == rule_id]
        if metric_code:
            rows = [row for row in rows if row.get("指标编号") == metric_code]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def execute(self, rule_id: int, trigger: str = "新执行") -> tuple[dict[str, Any] | None, str]:
        """按规则当前确认的口径版本执行一次聚合，生成一条新的结果记录。"""
        with store.lock:
            rule = store.find(MODULE, rule_id)
            if rule is None:
                return None, f"聚合规则 {rule_id} 不存在或已归档"
            if rule.get("status") != "已启用":
                return None, f"规则 {rule.get('规则编号')} 当前状态为{rule.get('status')}，请先启用规则再{trigger}"
            metric_code = str(rule.get("目标指标") or "")
            version_text = str(rule.get("口径版本") or "").strip()
            normalized = normalize_version(version_text)
            version_row = find_version(metric_code, normalized) if normalized else None
            if version_row is not None and version_row.get("status") == "已发布":
                formula = str(version_row.get("计算公式") or "")
                precision_raw = str(version_row.get("精度位数") or "")
                source = "发布确认"
            else:
                metric = next(
                    (row for row in store.rows(METRIC_MODULE) if row.get("指标编号") == metric_code),
                    None,
                )
                formula = str((metric or {}).get("计算公式") or "（未找到口径定义）")
                precision_raw = str((metric or {}).get("精度位数") or "")
                source = "历史遗留"
            try:
                precision = max(0, int(precision_raw))
            except ValueError:
                precision = 2
            seq = max((int(row.get("id", 0)) for row in store.rows(RESULT_TABLE)), default=0) + 1
            base = (rule_id * 997 + seq * 131 + (version_sort_key(version_text) + 1) * 17) % 100000
            result: dict[str, Any] = {
                "id": seq,
                "结果编号": f"RES-{seq:04d}",
                "规则id": rule_id,
                "规则编号": rule.get("规则编号"),
                "指标编号": metric_code,
                "口径版本": version_text or "（空）",
                "版本来源": source,
                "触发方式": trigger,
                "计算公式": formula,
                "结果值": round(base / 3, precision),
                "执行时间": _now(),
                "status": "已完成",
                "pending": False,
                "abnormal": False,
            }
            store.rows(RESULT_TABLE).append(result)
        return result, f"{trigger}完成：结果 {result['结果编号']} 按口径版本 {result['口径版本']}（{source}）记录"

    def recalculate(self, rule_id: int) -> tuple[dict[str, Any] | None, str]:
        """用户主动重算：生成新的结果记录，历史结果保留当时口径不动。"""
        return self.execute(rule_id, trigger="重算")
