"""指标定义接口：维护指标口径，覆盖提交审核、生效发布、废弃下线等动作。

口径版本化接口（/versions、/releases）必须声明在 /{entry_id} 之前：
/{entry_id} 是单段路径，先声明会把 "versions"、"export" 当成 entry_id 抢走。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.metricdef import MetricdefService
from app.services.metricversion import MetricVersionService

router = APIRouter(prefix="/api/metricdef", tags=["指标定义"])

service = MetricdefService()
version_service = MetricVersionService()

LIST_FIELDS = ["指标编号", "指标名称", "计算公式", "统计粒度", "时间窗口类型", "筛选条件", "精度位数", "口径版本"]
STATUSES = ["草稿", "待审核", "已生效", "已废弃"]


# ---------- 口径版本与发布（字面量路径，须在 /{entry_id} 之前） ----------

@router.get("/versions", response_model=PageResult[dict])
def list_versions(
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    status: str | None = Query(default=None, description="草稿、已发布"),
    page: int = 1,
    size: int = 50,
) -> PageResult[dict]:
    """按指标编号列出口径版本，草稿与已发布分开维护。"""
    items, total = version_service.list_versions(metric_code=metric_code, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/versions", response_model=ActionResult)
def create_version(payload: EntryPayload) -> ActionResult:
    """登记草稿版本：版本号由系统按指标编号分配，并发登记不会撞号。"""
    entry, message = version_service.create_draft(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/versions/{version_id}/diff")
def diff_version(version_id: int) -> dict[str, Any]:
    """查看该版本与上一相邻版本在计算公式、统计粒度、时间窗口、精度上的差异。"""
    payload, message = version_service.diff_with_previous(version_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=message)
    return payload


@router.get("/releases", response_model=PageResult[dict])
def list_releases(
    metric_code: str | None = Query(default=None, description="按指标编号过滤"),
    page: int = 1,
    size: int = 50,
) -> PageResult[dict]:
    """列出发布批次及每条聚合规则的确认结果。"""
    items, total = version_service.list_releases(metric_code=metric_code, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/releases", response_model=ActionResult)
def create_release(payload: EntryPayload) -> ActionResult:
    """发起发布：把正在使用该指标的聚合规则纳入影响确认范围，生成待确认批次。"""
    try:
        version_id = int(payload.values.get("版本id"))
    except (TypeError, ValueError):
        return ActionResult(ok=False, message="缺少待发布的版本id")
    operator = str(payload.values.get("操作人") or "").strip()
    batch, message = version_service.create_release(version_id, operator)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/releases/{batch_id}/confirm", response_model=ActionResult)
def confirm_release(batch_id: int, payload: EntryPayload) -> ActionResult:
    """确认发布：版本与全部规则确认结果作为同一业务提交生效；重复提交不产生重复版本。"""
    decisions = payload.values.get("decisions") or []
    if not isinstance(decisions, list):
        return ActionResult(ok=False, message="decisions 必须是数组，元素为 {规则id, 决策}")
    idem_key = str(payload.values.get("幂等键") or "").strip()
    batch, message = version_service.confirm_release(batch_id, decisions, idem_key)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.post("/releases/{batch_id}/cancel", response_model=ActionResult)
def cancel_release(batch_id: int) -> ActionResult:
    """作废待确认批次：版本保持草稿，聚合规则不受影响。"""
    batch, message = version_service.cancel_release(batch_id)
    if batch is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=batch)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出指标定义清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "metricdef", "total": total, "items": items}


# ---------- 指标口径本身的增查与状态流转 ----------

@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按指标编号检索"),
    status: str | None = Query(default=None, description="草稿、待审核、已生效、已废弃"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按指标编号与状态过滤指标定义列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条指标口径明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"指标口径 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条指标口径，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="指标口径已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条指标口径执行提交审核、生效发布、废弃下线；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
