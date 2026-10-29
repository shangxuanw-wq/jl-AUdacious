import { useCallback, useEffect, useState } from 'react'
import { api, dt } from '../api.js'
import { Badge, CANDIDATE_STATUS, issueText } from '../labels.jsx'

const FAULTS = [
  ['503 兩次', [{ status: 503 }, { status: 503 }]],
  ['429', [{ status: 429 }]],
  ['逾時（35 秒）', [{ delay: 35 }]],
  ['409 event_in_flight', [{ status: 409, code: 'event_in_flight' }]],
  ['503 維修中（Retry-After 600）', [{ status: 503, code: 'maintenance', retry_after: 600 }]],
  ['503 未啟用（不重送）', [{ status: 503, code: 'disabled' }]],
  ['503 八次（會放棄）', Array(8).fill({ status: 503 })],
]

export default function MockPanel() {
  const [s, setS] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => api('/mock-aud/_admin/state').then(setS).catch((e) => setError(e.message)), [])
  useEffect(() => { load() }, [load])

  const act = async (fn) => {
    setBusy(true)
    setError('')
    try {
      await fn()
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  if (!s) return <p className="text-sm text-stone-500">{error || '載入中…'}</p>

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">假澳得仕</h1>
          <p className="text-sm text-stone-500">開發用的對方系統：照契約 2026-10-29.5 回應。這裡可以模擬澳得仕人員發布／退回，或讓下一次請求故障。</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-ghost" onClick={load} disabled={busy}>重新整理</button>
          <button className="btn-danger" disabled={busy} onClick={() => window.confirm('清掉所有候選、紀錄與故障，6 張預設詢價單回到初始狀態？') && act(() => api('/mock-aud/_admin/reset', { method: 'POST' }))}>重設</button>
        </div>
      </div>
      {!s.token_configured && <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">MOCK_AUD_TOKEN 還沒設定：假 API 會回 503。</p>}
      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      <section className="card space-y-3 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium">讓接下來的請求故障：</span>
          {FAULTS.map(([label, next]) => (
            <button key={label} className="btn-ghost px-2.5 py-1 text-xs" disabled={busy} onClick={() => act(() => api('/mock-aud/_admin/faults', { method: 'POST', body: { next } }))}>{label}</button>
          ))}
          {s.faults.length > 0 && (
            <button className="btn-danger px-2.5 py-1 text-xs" disabled={busy} onClick={() => act(() => api('/mock-aud/_admin/faults', { method: 'DELETE' }))}>清除</button>
          )}
        </div>
        <p className="text-xs text-stone-500">
          排隊中的故障：{s.faults.length ? s.faults.map((f) => (f.status ? `${f.status}${f.code ? ' ' + f.code : ''}` : `延遲 ${f.delay}s`)).join(' → ') : '無'}
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="font-bold">詢價單與候選報價</h2>
        {s.rfqs.map((r) => (
          <div key={r.number} className="card p-4">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono font-medium">{r.number}</span>
              <span className="text-sm text-stone-600">{r.item_name}｜{r.material_text}｜{r.quantity} {r.unit}</span>
              <span className="inline-flex items-center gap-1 text-xs text-stone-600">
                規格版次 {r.spec_revision}
                <button className="btn-ghost px-1.5 py-0 text-xs" disabled={busy} onClick={() => act(() => api(`/mock-aud/_admin/rfqs/${r.number}`, { method: 'PATCH', body: { spec_revision: r.spec_revision + 1 } }))}>＋1</button>
              </span>
              <label className="inline-flex items-center gap-1 text-xs text-stone-600">
                <input type="checkbox" checked={!!r.is_test} disabled={busy} onChange={(e) => act(() => api(`/mock-aud/_admin/rfqs/${r.number}`, { method: 'PATCH', body: { is_test: e.target.checked } }))} />測試單
              </label>
              <select
                className="input ml-auto w-auto py-1 text-xs"
                value={r.send_pending ? 'send_pending' : r.snapshot ? r.status : 'no_snapshot'}
                disabled={busy}
                onChange={(e) => {
                  const v = e.target.value
                  const body = v === 'send_pending' ? { status: 'preparing', send_pending: true, snapshot: true } : v === 'no_snapshot' ? { status: 'sent', send_pending: false, snapshot: false } : { status: v, send_pending: false, snapshot: true }
                  act(() => api(`/mock-aud/_admin/rfqs/${r.number}`, { method: 'PATCH', body }))
                }}
              >
                <option value="sent">已寄出（收報價）</option>
                <option value="quoted">已有發布的報價</option>
                <option value="preparing">還沒寄出（409 status）</option>
                <option value="send_pending">寄送確認中（409 send_pending）</option>
                <option value="no_snapshot">沒有寄出紀錄（409 no_snapshot）</option>
                <option value="closed">已結案（409 closed）</option>
              </select>
            </div>
            {r.candidates.length > 0 && (
              <table className="mt-3 w-full">
                <thead>
                  <tr>
                    <th className="th">版</th>
                    <th className="th">修訂</th>
                    <th className="th">狀態</th>
                    <th className="th">待審原因</th>
                    <th className="th">收到</th>
                    <th className="th"></th>
                  </tr>
                </thead>
                <tbody>
                  {r.candidates.map((c) => (
                    <tr key={c.id}>
                      <td className="td num">{c.revision}</td>
                      <td className="td num">{c.quote_revision ?? '—'}</td>
                      <td className="td"><Badge map={CANDIDATE_STATUS} value={c.status} /></td>
                      <td className="td text-xs">{c.issues.filter((i) => i.level === 'review').map((i) => issueText(i.code)).join('、') || '—'}</td>
                      <td className="td text-xs">{dt(c.received_at)}</td>
                      <td className="td text-right">
                        {c.status === 'pending' && (
                          <span className="inline-flex gap-1.5">
                            <button className="btn-primary px-2.5 py-1 text-xs" disabled={busy} onClick={() => act(() => api(`/mock-aud/_admin/rfqs/${r.number}/candidates/${c.id}/publish`, { method: 'POST' }))}>發布</button>
                            <button className="btn-ghost px-2.5 py-1 text-xs" disabled={busy} onClick={() => act(() => api(`/mock-aud/_admin/rfqs/${r.number}/candidates/${c.id}/reject`, { method: 'POST' }))}>退回</button>
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </section>

      <section className="space-y-2">
        <h2 className="font-bold">最近收到的請求</h2>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[640px]">
            <thead className="bg-stone-50">
              <tr>
                <th className="th">時間</th>
                <th className="th">HTTP</th>
                <th className="th">詢價</th>
                <th className="th">event_id</th>
                <th className="th">request_id</th>
                <th className="th">故障</th>
              </tr>
            </thead>
            <tbody>
              {s.log.length === 0 && <tr><td className="td text-stone-500" colSpan={6}>還沒有請求</td></tr>}
              {s.log.map((l) => (
                <tr key={l.id}>
                  <td className="td text-xs">{dt(l.at)}</td>
                  <td className="td num">{l.status}</td>
                  <td className="td font-mono text-xs">{l.rfq || '—'}</td>
                  <td className="td font-mono text-xs">{l.event_id || '—'}</td>
                  <td className="td font-mono text-xs">{l.request_id}</td>
                  <td className="td text-xs">{l.fault ? JSON.stringify(l.fault) : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
