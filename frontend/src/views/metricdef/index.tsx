import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/metricdef'
const columns = [
  "指标编号",
  "指标名称",
  "计算公式",
  "统计粒度",
  "时间窗口类型",
  "筛选条件",
  "精度位数",
  "口径版本",
  "版本状态",
  "最新发布版本"
]
const actions = [
  "提交审核",
  "生效发布",
  "废弃下线"
]
const stats = [
  {
    "label": "指标定义总数",
    "value": 0
  },
  {
    "label": "已生效指标",
    "value": 0
  },
  {
    "label": "待审核指标",
    "value": 0
  }
]
const draftFields = ["指标名称", "计算公式", "统计粒度", "时间窗口类型", "精度位数", "筛选条件"]

type Row = Record<string, string | number | null>

interface VersionRow {
  id: number
  指标编号: string
  版本号: string
  status: string
  指标名称: string
  计算公式: string
  统计粒度: string
  时间窗口类型: string
  精度位数: string
  筛选条件?: string
  来源: string
  发布批次: string
  发布时间: string
}

interface ReleaseItem {
  规则id: number
  规则编号: string
  原版本: string
  决策: string
  确认后版本: string
}

interface ReleaseBatch {
  id: number
  批次号: string
  版本id: number
  指标编号: string
  版本号: string
  status: string
  items: ReleaseItem[]
  操作人: string
  提交时间: string
  生效时间: string
  失败原因?: string
}

interface DiffItem {
  字段: string
  上一版本: string
  本版本: string
  有变化: boolean
}

interface DiffResult {
  指标编号: string
  版本号: string
  对比版本号: string
  items: DiffItem[]
}

export default function MetricdefView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [noticeMessage, setNoticeMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const [selectedMetric, setSelectedMetric] = useState('')
  const [versions, setVersions] = useState<VersionRow[]>([])
  const [releases, setReleases] = useState<ReleaseBatch[]>([])
  const [diff, setDiff] = useState<DiffResult | null>(null)
  const [showDraftForm, setShowDraftForm] = useState(false)
  const [draftForm, setDraftForm] = useState<Record<string, string>>({})
  const [confirming, setConfirming] = useState<ReleaseBatch | null>(null)
  const [decisions, setDecisions] = useState<Record<number, string>>({})

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('指标口径列表读取失败')
      }
      const payload = await response.json()
      const items: Row[] = payload.items ?? []
      setRows(items)
      setTotal(payload.total ?? 0)
      setSelectedMetric((prev) => prev || String(items[0]?.['指标编号'] ?? ''))
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标定义列表读取失败')
    }
  }, [filters])

  const reloadVersions = useCallback(async (metricCode: string) => {
    if (!metricCode) {
      setVersions([])
      return
    }
    try {
      const response = await request(`${ENDPOINT}/versions?metric_code=${encodeURIComponent(metricCode)}`)
      if (!response.ok) {
        throw new Error('口径版本列表读取失败')
      }
      const payload = await response.json()
      setVersions(payload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '口径版本列表读取失败')
    }
  }, [])

  const reloadReleases = useCallback(async () => {
    try {
      const response = await request(`${ENDPOINT}/releases`)
      if (!response.ok) {
        throw new Error('发布记录读取失败')
      }
      const payload = await response.json()
      setReleases(payload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '发布记录读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
    void reloadReleases()
  }, [reload, reloadReleases])

  useEffect(() => {
    void reloadVersions(selectedMetric)
    setDiff(null)
  }, [selectedMetric, reloadVersions])

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
        throw new Error('指标定义动作未生效，请稍后重试')
      }
      await readAction(response, '指标定义动作未生效，请稍后重试')
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '指标定义操作失败')
    }
  }

  async function createDraft() {
    try {
      const response = await request(`${ENDPOINT}/versions`, {
        method: 'POST',
        body: JSON.stringify({ values: { ...draftForm, 指标编号: selectedMetric } }),
      })
      const payload = await readAction(response, '草稿版本登记失败')
      if (!payload) {
        return
      }
      setShowDraftForm(false)
      setDraftForm({})
      await reloadVersions(selectedMetric)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '草稿版本登记失败')
    }
  }

  async function showDiff(version: VersionRow) {
    try {
      const response = await request(`${ENDPOINT}/versions/${version.id}/diff`)
      if (!response.ok) {
        const payload = await response.json()
        throw new Error(payload.detail ?? '版本差异读取失败')
      }
      setDiff(await response.json())
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '版本差异读取失败')
    }
  }

  async function startPublish(version: VersionRow) {
    try {
      const response = await request(`${ENDPOINT}/releases`, {
        method: 'POST',
        body: JSON.stringify({ values: { 版本id: version.id, 操作人: '值班管理员' } }),
      })
      const payload = await readAction(response, '发布批次创建失败')
      if (!payload) {
        return
      }
      const batch: ReleaseBatch = payload.entry
      setConfirming(batch)
      const initial: Record<number, string> = {}
      for (const item of batch.items ?? []) {
        initial[item.规则id] = item.决策 || '保留旧版'
      }
      setDecisions(initial)
      await reloadReleases()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '发布批次创建失败')
    }
  }

  async function confirmRelease(batch: ReleaseBatch, decisionMap: Record<number, string>) {
    try {
      const response = await request(`${ENDPOINT}/releases/${batch.id}/confirm`, {
        method: 'POST',
        body: JSON.stringify({
          values: {
            decisions: Object.entries(decisionMap).map(([ruleId, decision]) => ({ 规则id: Number(ruleId), 决策: decision })),
            幂等键: batch.批次号,
          },
        }),
      })
      const payload = await readAction(response, '发布确认失败')
      if (!payload) {
        return
      }
      setConfirming(null)
      await Promise.all([reload(), reloadVersions(selectedMetric), reloadReleases()])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '发布确认失败')
    }
  }

  async function resubmitRelease(batch: ReleaseBatch) {
    // 幂等验证：按批次里已存的确认结果原样再提交一次，不应产生重复版本
    const decisionMap: Record<number, string> = {}
    for (const item of batch.items ?? []) {
      decisionMap[item.规则id] = item.决策
    }
    await confirmRelease(batch, decisionMap)
  }

  async function cancelRelease(batch: ReleaseBatch) {
    try {
      const response = await request(`${ENDPOINT}/releases/${batch.id}/cancel`, { method: 'POST' })
      const payload = await readAction(response, '发布批次作废失败')
      if (!payload) {
        return
      }
      if (confirming?.id === batch.id) {
        setConfirming(null)
      }
      await reloadReleases()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '发布批次作废失败')
    }
  }

  return (
    <section className="page" data-module="metricdef">
      <header className="page-head">
        <div>
          <h2>指标定义管理</h2>
          <p className="page-desc">维护指标口径的输入、执行约束与结果记录，为指标定义提供可验证的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('指标口径登记入口尚未接入审批流')}>
            登记指标口径
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出指标定义清单
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
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无指标定义数据，可先登记指标口径</td>
            </tr>
          )}
        </tbody>
      </table>

      <section className="sub-panel">
        <header className="panel-head">
          <h3>口径版本管理</h3>
          <div className="page-actions">
            <label className="filter-item">
              <span>指标编号</span>
              <select value={selectedMetric} onChange={(event) => setSelectedMetric(event.target.value)}>
                {rows.map((row) => (
                  <option key={String(row['指标编号'])} value={String(row['指标编号'] ?? '')}>
                    {row['指标编号']}（{row['指标名称']}）
                  </option>
                ))}
              </select>
            </label>
            <button className="btn primary" type="button" onClick={() => setShowDraftForm((prev) => !prev)}>
              {showDraftForm ? '收起草稿表单' : '新建草稿版本'}
            </button>
          </div>
        </header>

        {showDraftForm && (
          <form
            className="filter-bar"
            onSubmit={(event) => { event.preventDefault(); void createDraft() }}
          >
            {draftFields.map((field) => (
              <label key={field} className="filter-item">
                <span>{field}</span>
                <input
                  value={draftForm[field] ?? ''}
                  placeholder={`填写${field}`}
                  onChange={(event) => setDraftForm((prev) => ({ ...prev, [field]: event.target.value }))}
                />
              </label>
            ))}
            <button className="btn primary" type="submit">登记草稿</button>
          </form>
        )}

        <table className="data-table">
          <thead>
            <tr>
              <th>版本号</th>
              <th>状态</th>
              <th>计算公式</th>
              <th>统计粒度</th>
              <th>时间窗口类型</th>
              <th>精度位数</th>
              <th>来源</th>
              <th>发布批次</th>
              <th>发布时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {versions.map((version) => (
              <tr key={version.id}>
                <td>{version.版本号}</td>
                <td>{version.status}</td>
                <td>{version.计算公式}</td>
                <td>{version.统计粒度}</td>
                <td>{version.时间窗口类型}</td>
                <td>{version.精度位数}</td>
                <td>{version.来源}</td>
                <td>{version.发布批次 || '—'}</td>
                <td>{version.发布时间 || '—'}</td>
                <td className="row-actions">
                  <button className="link" type="button" onClick={() => void showDiff(version)}>与上一版对比</button>
                  {version.status === '草稿' && (
                    <button className="link" type="button" onClick={() => void startPublish(version)}>发布</button>
                  )}
                </td>
              </tr>
            ))}
            {versions.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={10}>该指标还没有口径版本，可先新建草稿版本</td>
              </tr>
            )}
          </tbody>
        </table>

        {diff && (
          <div className="diff-panel">
            <h4>口径差异：{diff.对比版本号} → {diff.版本号}（{diff.指标编号}）</h4>
            <table className="data-table">
              <thead>
                <tr>
                  <th>字段</th>
                  <th>{diff.对比版本号}</th>
                  <th>{diff.版本号}</th>
                  <th>是否变化</th>
                </tr>
              </thead>
              <tbody>
                {diff.items.map((item) => (
                  <tr key={item.字段} className={item.有变化 ? 'diff-changed' : ''}>
                    <td>{item.字段}</td>
                    <td>{item.上一版本}</td>
                    <td>{item.本版本}</td>
                    <td>{item.有变化 ? '有变化' : '一致'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {confirming && (
        <section className="sub-panel confirm-panel">
          <header className="panel-head">
            <h3>影响确认：批次 {confirming.批次号}（{confirming.指标编号} {confirming.版本号}）</h3>
            <span className="page-desc">以下聚合规则正在使用该指标，请逐条确认保留旧版还是切换新版，确认后作为同一业务提交生效。</span>
          </header>
          <table className="data-table">
            <thead>
              <tr>
                <th>规则编号</th>
                <th>当前口径版本</th>
                <th>确认决策</th>
              </tr>
            </thead>
            <tbody>
              {confirming.items.map((item) => (
                <tr key={item.规则id}>
                  <td>{item.规则编号}</td>
                  <td>{item.原版本}</td>
                  <td>
                    <label className="radio-item">
                      <input
                        type="radio"
                        name={`decision-${item.规则id}`}
                        checked={(decisions[item.规则id] ?? '保留旧版') === '保留旧版'}
                        onChange={() => setDecisions((prev) => ({ ...prev, [item.规则id]: '保留旧版' }))}
                      />
                      保留旧版（{item.原版本}）
                    </label>
                    <label className="radio-item">
                      <input
                        type="radio"
                        name={`decision-${item.规则id}`}
                        checked={decisions[item.规则id] === '切换新版'}
                        onChange={() => setDecisions((prev) => ({ ...prev, [item.规则id]: '切换新版' }))}
                      />
                      切换新版（{confirming.版本号}）
                    </label>
                  </td>
                </tr>
              ))}
              {confirming.items.length === 0 && (
                <tr>
                  <td className="empty-state" colSpan={3}>没有聚合规则使用该指标，可直接确认发布</td>
                </tr>
              )}
            </tbody>
          </table>
          <div className="page-actions confirm-actions">
            <button className="btn primary" type="button" onClick={() => void confirmRelease(confirming, decisions)}>
              确认发布（{confirming.items.length} 条规则一并生效）
            </button>
            <button className="btn ghost" type="button" onClick={() => setConfirming(null)}>暂不确认</button>
          </div>
        </section>
      )}

      <section className="sub-panel">
        <header className="panel-head">
          <h3>发布记录</h3>
          <span className="page-desc">每次发布的版本与全部规则确认结果作为同一业务提交生效；重复提交不会产生重复版本。</span>
        </header>
        <table className="data-table">
          <thead>
            <tr>
              <th>批次号</th>
              <th>指标编号</th>
              <th>版本号</th>
              <th>状态</th>
              <th>确认明细</th>
              <th>提交时间</th>
              <th>生效时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {releases.map((batch) => (
              <tr key={batch.id}>
                <td>{batch.批次号}</td>
                <td>{batch.指标编号}</td>
                <td>{batch.版本号}</td>
                <td>{batch.status}{batch.失败原因 ? `（${batch.失败原因}）` : ''}</td>
                <td>
                  {(batch.items ?? []).length === 0 && '—'}
                  {(batch.items ?? []).map((item) => (
                    <div key={item.规则id}>
                      {item.规则编号}：{item.原版本} → {item.确认后版本}（{item.决策}）
                    </div>
                  ))}
                </td>
                <td>{batch.提交时间}</td>
                <td>{batch.生效时间 || '—'}</td>
                <td className="row-actions">
                  {batch.status === '待确认' && (
                    <>
                      <button className="link" type="button" onClick={() => { setConfirming(batch); const m: Record<number, string> = {}; for (const i of batch.items ?? []) { m[i.规则id] = i.决策 || '保留旧版' } setDecisions(m) }}>继续确认</button>
                      <button className="link" type="button" onClick={() => void cancelRelease(batch)}>作废</button>
                    </>
                  )}
                  {batch.status === '已生效' && (
                    <button className="link" type="button" onClick={() => void resubmitRelease(batch)}>再次提交（幂等验证）</button>
                  )}
                </td>
              </tr>
            ))}
            {releases.length === 0 && (
              <tr>
                <td className="empty-state" colSpan={8}>暂无发布记录</td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      <footer className="page-foot">
        <span>共 {total} 条指标定义记录</span>
        {noticeMessage && <span className="notice-text">{noticeMessage}</span>}
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
