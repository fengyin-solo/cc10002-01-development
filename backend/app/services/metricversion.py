"""指标口径版本与发布：草稿版本、相邻版本差异、发布批次与影响确认。

设计要点：
- 版本号归一化：'v2'、'V2'、'2'、'2.0' 都归一成 'v2'；历史样例里的非规范文字
  （如「指标定义样例1」）归一化结果为 None，只能算「未归档」，绝不当成最新版本。
- 发布 = 一个业务提交：版本状态、全部聚合规则的确认结果、批次状态在同一个锁内
  一次性生效；任何校验不通过都不落半个改动。
- 幂等：同一版本重复发起发布会拿到同一个待确认批次；同一批次重复确认直接返回
  已生效结果，不产生重复版本；版本号按指标编号在锁内分配，并发不会撞号。
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.store import store

VERSION_TABLE = "metric_version"
RELEASE_TABLE = "metric_release"
METRIC_MODULE = "metricdef"
AGG_MODULE = "aggregation"

# 相邻版本对比只关注口径四要素：计算公式、统计粒度、时间窗口、精度
DIFF_FIELDS = ["计算公式", "统计粒度", "时间窗口类型", "精度位数"]
VERSION_REQUIRED = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口类型", "精度位数"]
DECISION_KEEP = "保留旧版"
DECISION_SWITCH = "切换新版"
DECISIONS = {DECISION_KEEP, DECISION_SWITCH}

_VERSION_RE = re.compile(r"^[vV]?(\d+)(?:\.0+)?$")


def normalize_version(text: Any) -> str | None:
    """把 'v2'、'V2'、'2'、'2.0' 归一成 'v2'；其它文字返回 None（非规范口径）。"""
    match = _VERSION_RE.match(str(text or "").strip())
    if not match:
        return None
    return f"v{int(match.group(1))}"


def version_sort_key(text: Any) -> int:
    """版本排序键；非规范文字排最前（-1），保证不会被当成最新版本。"""
    normalized = normalize_version(text)
    return int(normalized[1:]) if normalized else -1


def find_version(metric_code: str, version_no: Any) -> dict[str, Any] | None:
    """按指标编号 + 版本号找版本记录；版本号先归一化再比。"""
    target = normalize_version(version_no)
    if target is None:
        return None
    for row in store.rows(VERSION_TABLE):
        if row.get("指标编号") == metric_code and normalize_version(row.get("版本号")) == target:
            return row
    return None


def latest_published_version(metric_code: str) -> dict[str, Any] | None:
    """指标当前最新已发布版本；没有任何已发布版本时返回 None。"""
    published = [
        row for row in store.rows(VERSION_TABLE)
        if row.get("指标编号") == metric_code and row.get("status") == "已发布"
    ]
    if not published:
        return None
    return max(published, key=lambda row: version_sort_key(row.get("版本号")))


def metric_version_state(raw_text: Any) -> str:
    """指标定义/聚合规则上一段口径版本文字的状态：已归档 or 未归档。"""
    return "已归档" if normalize_version(raw_text) is not None else "未归档"


def rule_version_state(rule: dict[str, Any]) -> str:
    """聚合规则口径版本的确认状态，供列表页直接展示。"""
    raw = str(rule.get("口径版本") or "").strip()
    if not raw:
        return "未设置"
    normalized = normalize_version(raw)
    if normalized is None:
        return "未归档"
    found = find_version(str(rule.get("目标指标") or ""), normalized)
    if found is not None and found.get("status") == "已发布":
        return "已确认"
    return "待核实"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _next_id(table: str) -> int:
    return max((int(row.get("id", 0)) for row in store.rows(table)), default=0) + 1


class MetricVersionService:
    """口径版本、版本差异、发布批次的业务规则都收在这里。"""

    # ---------- 版本 ----------

    def list_versions(
        self,
        *,
        metric_code: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(VERSION_TABLE)
        if metric_code:
            rows = [row for row in rows if row.get("指标编号") == metric_code]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        rows = sorted(rows, key=lambda row: (row.get("指标编号", ""), version_sort_key(row.get("版本号"))))
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def create_draft(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记草稿版本：版本号在锁内按指标编号自增分配，并发也不会撞号。"""
        missing = [field for field in VERSION_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        metric_code = str(values["指标编号"]).strip()
        with store.lock:
            if not any(row.get("指标编号") == metric_code for row in store.rows(METRIC_MODULE)):
                return None, f"指标编号 {metric_code} 在指标定义中不存在，请先在指标定义登记"
            siblings = [row for row in store.rows(VERSION_TABLE) if row.get("指标编号") == metric_code]
            next_no = max([version_sort_key(row.get("版本号")) for row in siblings] + [0]) + 1
            entry: dict[str, Any] = {
                "id": _next_id(VERSION_TABLE),
                "指标编号": metric_code,
                "版本号": f"v{next_no}",
                "status": "草稿",
                "来源": "新建草稿",
                "发布批次": "",
                "发布时间": "",
                "pending": True,
                "abnormal": False,
            }
            for field in VERSION_REQUIRED:
                if field != "指标编号":
                    entry[field] = str(values.get(field) or "").strip()
            entry["筛选条件"] = str(values.get("筛选条件") or "").strip()
            store.rows(VERSION_TABLE).append(entry)
        return entry, f"草稿版本 {entry['版本号']} 已登记，确认无误后可发起发布"

    def diff_with_previous(self, version_id: int) -> tuple[dict[str, Any] | None, str]:
        """与上一相邻版本对比口径四要素；没有上一版本时明确说明。"""
        version = None
        for row in store.rows(VERSION_TABLE):
            if int(row.get("id", 0)) == version_id:
                version = row
                break
        if version is None:
            return None, f"口径版本 {version_id} 不存在"
        current_key = version_sort_key(version.get("版本号"))
        predecessors = [
            row for row in store.rows(VERSION_TABLE)
            if row.get("指标编号") == version.get("指标编号")
            and int(row.get("id", 0)) != version_id
            and version_sort_key(row.get("版本号")) < current_key
        ]
        if not predecessors:
            return None, f"版本 {version.get('版本号')} 是 {version.get('指标编号')} 的第一个版本，没有可对比的上一版本"
        previous = max(predecessors, key=lambda row: version_sort_key(row.get("版本号")))
        items = [
            {
                "字段": field,
                "上一版本": previous.get(field) or "（空）",
                "本版本": version.get(field) or "（空）",
                "有变化": str(previous.get(field) or "") != str(version.get(field) or ""),
            }
            for field in DIFF_FIELDS
        ]
        payload = {
            "指标编号": version.get("指标编号"),
            "版本号": version.get("版本号"),
            "对比版本号": previous.get("版本号"),
            "items": items,
        }
        return payload, f"已生成 {previous.get('版本号')} → {version.get('版本号')} 的口径差异"

    # ---------- 发布批次 ----------

    def list_releases(
        self,
        *,
        metric_code: str | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(RELEASE_TABLE)
        if metric_code:
            rows = [row for row in rows if row.get("指标编号") == metric_code]
        rows = sorted(rows, key=lambda row: int(row.get("id", 0)), reverse=True)
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def create_release(self, version_id: int, operator: str) -> tuple[dict[str, Any] | None, str]:
        """发起发布：生成待确认批次，把正在使用该指标的聚合规则纳入影响确认范围。

        幂等约束：
        - 同一草稿版本重复发起，直接返回已存在的待确认批次；
        - 已发布版本不允许再次发布；
        - 同一指标同时只允许一个待确认批次，避免并发发布口径互相覆盖。
        """
        with store.lock:
            version = None
            for row in store.rows(VERSION_TABLE):
                if int(row.get("id", 0)) == version_id:
                    version = row
                    break
            if version is None:
                return None, f"口径版本 {version_id} 不存在"
            if version.get("status") == "已发布":
                return None, f"版本 {version.get('版本号')} 已发布，请勿重复发布"
            if version.get("status") != "草稿":
                return None, f"版本 {version.get('版本号')} 当前状态为{version.get('status')}，不能发起发布"
            metric_code = str(version.get("指标编号") or "")
            for batch in store.rows(RELEASE_TABLE):
                if batch.get("status") != "待确认":
                    continue
                if int(batch.get("版本id", 0)) == version_id:
                    return batch, f"发布批次 {batch.get('批次号')} 已存在且待确认，请直接确认"
                if batch.get("指标编号") == metric_code:
                    return None, (
                        f"指标 {metric_code} 存在待确认批次 {batch.get('批次号')}，"
                        "请先确认或作废该批次再发起新发布"
                    )
            items = []
            for rule in store.rows(AGG_MODULE):
                if str(rule.get("目标指标") or "") != metric_code:
                    continue
                current = str(rule.get("口径版本") or "").strip()
                if normalize_version(current) == normalize_version(version.get("版本号")):
                    continue  # 规则已经在该版本上，无需确认
                items.append({
                    "规则id": int(rule.get("id", 0)),
                    "规则编号": rule.get("规则编号"),
                    "原版本": current or "（空）",
                    "决策": DECISION_KEEP,  # 默认保留旧版，绝不悄悄替换
                    "确认后版本": current or "（空）",
                })
            today = datetime.now().strftime("%Y%m%d")
            batch: dict[str, Any] = {
                "id": _next_id(RELEASE_TABLE),
                "批次号": f"REL-{today}-{_next_id(RELEASE_TABLE):04d}",
                "版本id": version_id,
                "指标编号": metric_code,
                "版本号": version.get("版本号"),
                "status": "待确认",
                "items": items,
                "操作人": operator or "未填写",
                "幂等键": "",
                "提交时间": _now(),
                "生效时间": "",
                "失败原因": "",
                "pending": True,
                "abnormal": False,
            }
            store.rows(RELEASE_TABLE).append(batch)
        return batch, f"发布批次 {batch['批次号']} 已创建，{len(items)} 条聚合规则进入影响确认范围"

    def confirm_release(
        self,
        batch_id: int,
        decisions: list[dict[str, Any]],
        idem_key: str = "",
    ) -> tuple[dict[str, Any] | None, str]:
        """确认发布：版本 + 全部规则确认结果作为同一业务提交生效。

        - 重复确认同一批次：直接返回已生效结果，不产生重复版本；
        - 决策缺失/非法：批次保持待确认，可修正后重新提交；
        - 与已发布版本撞号（并发发布）：批次置为已失败，任何规则都不改动。
        """
        with store.lock:
            batch = None
            for row in store.rows(RELEASE_TABLE):
                if int(row.get("id", 0)) == batch_id:
                    batch = row
                    break
            if batch is None:
                return None, f"发布批次 {batch_id} 不存在"
            if batch.get("status") == "已生效":
                return batch, f"发布批次 {batch.get('批次号')} 已生效，本次重复提交未产生新版本"
            if batch.get("status") == "已作废":
                return None, f"发布批次 {batch.get('批次号')} 已作废，请重新发起发布"
            if batch.get("status") == "已失败":
                return None, f"发布批次 {batch.get('批次号')} 已失败（{batch.get('失败原因') or '原因未知'}），请重新发起发布"

            # 先完整校验，再统一落库：任何一步不通过都不改动规则
            decision_map: dict[int, str] = {}
            for item in decisions or []:
                try:
                    decision_map[int(item.get("规则id"))] = str(item.get("决策") or "").strip()
                except (TypeError, ValueError):
                    continue
            problems: list[str] = []
            plan: list[tuple[dict[str, Any], str, str]] = []  # (规则, 确认后版本, 决策)
            for item in batch.get("items", []):
                rule_id = int(item.get("规则id", 0))
                decision = decision_map.get(rule_id, "")
                if decision not in DECISIONS:
                    problems.append(f"规则 {item.get('规则编号')} 缺少有效确认决策（保留旧版/切换新版）")
                    continue
                rule = None
                for row in store.rows(AGG_MODULE):
                    if int(row.get("id", 0)) == rule_id:
                        rule = row
                        break
                if rule is None:
                    problems.append(f"规则 {item.get('规则编号')} 已不存在，无法确认")
                    continue
                if decision == DECISION_SWITCH:
                    plan.append((rule, str(batch.get("版本号")), decision))
                else:
                    plan.append((rule, str(item.get("原版本") or ""), decision))
            if problems:
                return None, "发布确认未通过，未改动任何规则：" + "；".join(problems)

            conflict = any(
                row.get("指标编号") == batch.get("指标编号")
                and row.get("status") == "已发布"
                and normalize_version(row.get("版本号")) == normalize_version(batch.get("版本号"))
                and int(row.get("id", 0)) != int(batch.get("版本id", 0))
                for row in store.rows(VERSION_TABLE)
            )
            if conflict:
                batch["status"] = "已失败"
                batch["abnormal"] = True
                batch["pending"] = False
                batch["失败原因"] = f"版本 {batch.get('版本号')} 已被其他发布占用，疑似并发发布"
                return None, f"发布确认失败：{batch['失败原因']}，未改动任何规则"

            # 同一业务提交：版本状态 + 全部规则确认结果 + 批次状态一次性生效
            version = None
            for row in store.rows(VERSION_TABLE):
                if int(row.get("id", 0)) == int(batch.get("版本id", 0)):
                    version = row
                    break
            if version is None:
                batch["status"] = "已失败"
                batch["abnormal"] = True
                batch["pending"] = False
                batch["失败原因"] = "待发布的口径版本已不存在"
                return None, f"发布确认失败：{batch['失败原因']}，未改动任何规则"
            now = _now()
            version["status"] = "已发布"
            version["发布批次"] = batch.get("批次号")
            version["发布时间"] = now
            version["pending"] = False
            switched = 0
            for rule, confirmed_version, decision in plan:
                if decision == DECISION_SWITCH:
                    rule["口径版本"] = confirmed_version
                    rule["版本确认批次"] = batch.get("批次号")
                    switched += 1
            for item in batch.get("items", []):
                decision = decision_map[int(item.get("规则id", 0))]
                item["决策"] = decision
                item["确认后版本"] = str(batch.get("版本号")) if decision == DECISION_SWITCH else str(item.get("原版本") or "")
            batch["status"] = "已生效"
            batch["生效时间"] = now
            batch["pending"] = False
            if idem_key:
                batch["幂等键"] = idem_key
        kept = len(plan) - switched
        return batch, (
            f"发布批次 {batch['批次号']} 已生效：版本 {batch.get('版本号')} 发布，"
            f"{switched} 条规则切换新版，{kept} 条保留旧版"
        )

    def cancel_release(self, batch_id: int) -> tuple[dict[str, Any] | None, str]:
        """作废待确认批次：版本保持草稿，规则不受影响。"""
        with store.lock:
            batch = None
            for row in store.rows(RELEASE_TABLE):
                if int(row.get("id", 0)) == batch_id:
                    batch = row
                    break
            if batch is None:
                return None, f"发布批次 {batch_id} 不存在"
            if batch.get("status") != "待确认":
                return None, f"发布批次 {batch.get('批次号')} 当前状态为{batch.get('status')}，不能作废"
            batch["status"] = "已作废"
            batch["pending"] = False
        return batch, f"发布批次 {batch['批次号']} 已作废，版本仍为草稿，可重新发起发布"
