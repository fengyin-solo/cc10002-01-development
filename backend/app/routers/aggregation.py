"""聚合查询接口：维护聚合规则，覆盖提交校验、启用规则、停用规则等动作。

/results 等字面量路径必须声明在 /{entry_id} 之前，否则会被路径参数抢走。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.aggregation import AggregationService

router = APIRouter(prefix="/api/aggregation", tags=["聚合查询"])

service = AggregationService()

LIST_FIELDS = ["规则编号", "聚合函数", "目标指标", "分组维度", "时间范围", "筛选条件", "采样比例", "缓存秒数"]
STATUSES = ["草稿", "待校验", "已启用", "已停用"]


# ---------- 聚合结果（字面量路径，须在 /{entry_id} 之前） ----------

@router.get("/results", response_model=PageResult[dict])
def list_results(
    rule_id: int | None = Query(default=None, description="按规则过滤"),
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    page: int = 1,
    size: int = 50,
) -> PageResult[dict]:
    """聚合结果记录：每条都保留当时的口径版本、版本来源与计算公式快照。"""
    items, total = service.list_results(rule_id=rule_id, metric_code=metric_code, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出聚合查询清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "aggregation", "total": total, "items": items}


# ---------- 聚合规则本身的增查与状态流转 ----------

@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按规则编号检索"),
    status: str | None = Query(default=None, description="草稿、待校验、已启用、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按规则编号与状态过滤聚合查询列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条聚合规则明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"聚合规则 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条聚合规则，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="聚合规则已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条聚合规则执行提交校验、启用规则、停用规则；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/execute", response_model=ActionResult)
def execute_entry(entry_id: int) -> ActionResult:
    """新执行：按规则当前确认的口径版本生成一条结果记录。"""
    result, message = service.execute(entry_id, trigger="新执行")
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)


@router.post("/{entry_id}/recalculate", response_model=ActionResult)
def recalculate_entry(entry_id: int) -> ActionResult:
    """主动重算：生成新的结果记录，历史结果保留当时口径及版本来源。"""
    result, message = service.recalculate(entry_id)
    if result is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=result)
