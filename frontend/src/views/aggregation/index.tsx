import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/aggregation'
const columns = [
  "规则编号",
  "聚合函数",
  "目标指标",
  "分组维度",
  "时间范围",
  "筛选条件",
  "采样比例",
  "缓存秒数",
  "口径版本",
  "版本状态"
]
const actions = [
  "提交校验",
  "启用规则",
  "停用规则"
]
const stats = [
  {
    "label": "聚合规则总数",
    "value": 0
  },
  {
    "label": "已启用规则",
    "value": 0
  },
  {
    "label": "待校验规则",
    "value": 0
  }
]

type Row = Record<string, string | number | null>

interface ResultRow {
  id: number
  结果编号: string
  规则id: number
  规则编号: string
  指标编号: string
  口径版本: string
  版本来源: string
  触发方式: string
  计算公式: string
  结果值: number
  执行时间: string
}

export default function AggregationView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [noticeMessage, setNoticeMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])
  const [resultRule, setResultRule] = useState<Row | null>(null)
  const [results, setResults] = useState<ResultRow[]>([])

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('聚合规则列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合查询列表读取失败')
    }
  }, [filters])

  const reloadResults = useCallback(async (rule: Row) => {
    try {
      const response = await request(`${ENDPOINT}/results?rule_id=${rule.id}`)
      if (!response.ok) {
        throw new Error('聚合结果读取失败')
      }
      const payload = await response.json()
      setResults(payload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合结果读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  async function readAction(response: Response, fallback: string) {
    const payload = await response.json()
    if (!payload.ok) {
      setErrorMessage(payload.message ?? fallback)
      setNoticeMessage('')
      return null
    }
    setNoticeMessage(payload.message ?? fallback)
    setErrorMessage('')
    return payload
  }

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ values: { action } }),
      })
      if (!response.ok) {
        throw new Error('聚合查询动作未生效，请稍后重试')
      }
      await readAction(response, '聚合查询动作未生效，请稍后重试')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合查询操作失败')
    }
  }

  async function runTrigger(trigger: 'execute' | 'recalculate', row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/${trigger}`, { method: 'POST' })
      const payload = await readAction(response, trigger === 'execute' ? '执行失败' : '重算失败')
      if (payload && resultRule?.id === row.id) {
        await reloadResults(row)
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '聚合执行操作失败')
    }
  }

  async function openResults(row: Row) {
    setResultRule(row)
    await reloadResults(row)
  }

  return (
    <section className="page" data-module="aggregation">
      <header className="page-head">
        <div>
          <h2>聚合查询管理</h2>
          <p className="page-desc">维护聚合规则的输入、执行约束与结果记录，为聚合查询提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('聚合规则登记入口尚未接入审批流')}>
            登记聚合规则
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出聚合查询清单
          </button>
        </div>
      </header>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
                <button className="link" type="button" onClick={() => void runTrigger('execute', row)}>执行</button>
                <button className="link" type="button" onClick={() => void runTrigger('recalculate', row)}>重算</button>
                <button className="link" type="button" onClick={() => void openResults(row)}>结果记录</button>
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无聚合查询数据，可先登记聚合规则</td>
            </tr>
          )}
        </tbody>
      </table>

      {resultRule && (
        <section className="sub-panel">
          <header className="panel-head">
            <h3>结果记录：{resultRule['规则编号']}（当前口径版本 {resultRule['口径版本'] || '—'}）</h3>
            <span className="page-desc">每条结果保留当时的口径版本、版本来源与计算公式快照；只有主动执行或重算才产生新记录。</span>
          </header>
          <table className="data-table">
            <thead>
              <tr>
                <th>结果编号</th>
                <th>口径版本</th>
                <th>版本来源</th>
                <th>触发方式</th>
                <th>计算公式</th>
                <th>结果值</th>
                <th>执行时间</th>
              </tr>
            </thead>
            <tbody>
              {results.map((result) => (
                <tr key={result.id}>
                  <td>{result.结果编号}</td>
                  <td>{result.口径版本}</td>
                  <td>{result.版本来源}</td>
                  <td>{result.触发方式}</td>
                  <td>{result.计算公式}</td>
                  <td>{result.结果值}</td>
                  <td>{result.执行时间}</td>
                </tr>
              ))}
              {results.length === 0 && (
                <tr>
                  <td className="empty-state" colSpan={7}>该规则还没有执行记录，可先执行一次</td>
                </tr>
              )}
            </tbody>
          </table>
        </section>
      )}

      <footer className="page-foot">
        <span>共 {total} 条聚合查询记录</span>
        {noticeMessage && <span className="notice-text">{noticeMessage}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
