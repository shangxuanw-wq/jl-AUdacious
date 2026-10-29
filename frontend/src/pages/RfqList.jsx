import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, dt } from '../api.js'
import { Badge, QUOTE_STATUS, RFQ_STATUS } from '../labels.jsx'

const EMPTY = { rfq_number: 'AUD-RFQ-2026-', item_name: '', material_text: '', quantity: 1, unit: 'pcs', need_date: '', sync_mock: true }

export default function RfqList() {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [saving, setSaving] = useState(false)
  const nav = useNavigate()

  const load = () => api('/rfqs').then((d) => setRows(d.rfqs)).catch((e) => setError(e.message))
  useEffect(() => { load() }, [])

  const set = (k) => (e) => {
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => {
      const next = { ...f, [k]: v }
      if (k === 'rfq_number' && (!f.item_name || f.item_name === `工件 ${f.rfq_number}-1`)) next.item_name = `工件 ${v}-1`
      return next
    })
  }

  const submit = async (e) => {
    e.preventDefault()
    setSaving(true)
    setError('')
    try {
      const r = await api('/rfqs', { method: 'POST', body: { ...form, quantity: Number(form.quantity), need_date: form.need_date || null } })
      nav(`/rfqs/${r.id}`)
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">詢價單</h1>
          <p className="text-sm text-stone-500">第 2 段完成前，詢價單先手動建立（照詢價信「工件1｜品名｜材質｜數量」原樣填）。</p>
        </div>
        <button className="btn-primary" onClick={() => setOpen((v) => !v)}>{open ? '收起' : '＋ 新增詢價單'}</button>
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {open && (
        <form onSubmit={submit} className="card grid gap-4 p-5 sm:grid-cols-6">
          <div className="sm:col-span-2">
            <label className="label">詢價編號</label>
            <input className="input font-mono" value={form.rfq_number} onChange={set('rfq_number')} required />
          </div>
          <div className="sm:col-span-4">
            <label className="label">品名（原樣）</label>
            <input className="input" value={form.item_name} onChange={set('item_name')} required />
          </div>
          <div className="sm:col-span-2">
            <label className="label">材質（原樣）</label>
            <input className="input" value={form.material_text} onChange={set('material_text')} required placeholder="例如 PLA" />
          </div>
          <div>
            <label className="label">數量</label>
            <input className="input num" type="number" min="1" value={form.quantity} onChange={set('quantity')} required />
          </div>
          <div>
            <label className="label">單位</label>
            <select className="input" value={form.unit} onChange={set('unit')}>
              <option value="pcs">pcs（件）</option>
              <option value="sets">sets（套）</option>
            </select>
          </div>
          <div className="sm:col-span-2">
            <label className="label">需求日（可空白）</label>
            <input className="input" type="date" value={form.need_date} onChange={set('need_date')} />
          </div>
          <label className="flex items-center gap-2 text-sm text-stone-600 sm:col-span-4">
            <input type="checkbox" checked={form.sync_mock} onChange={set('sync_mock')} />
            同時在「假澳得仕」建立這張詢價單（開發測試用）
          </label>
          <div className="flex justify-end sm:col-span-2">
            <button className="btn-primary" disabled={saving}>{saving ? '建立中…' : '建立'}</button>
          </div>
        </form>
      )}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[720px]">
          <thead className="bg-stone-50">
            <tr>
              <th className="th">詢價編號</th>
              <th className="th">品名／材質</th>
              <th className="th">數量</th>
              <th className="th">需求日</th>
              <th className="th">狀態</th>
              <th className="th">最新報價</th>
              <th className="th">建立時間</th>
            </tr>
          </thead>
          <tbody>
            {rows === null && (
              <tr><td className="td text-stone-500" colSpan={7}>載入中…</td></tr>
            )}
            {rows?.length === 0 && (
              <tr><td className="td text-stone-500" colSpan={7}>還沒有詢價單。按「新增詢價單」開始；測試可用 AUD-RFQ-2026-0099。</td></tr>
            )}
            {rows?.map((r) => (
              <tr key={r.id} className="hover:bg-stone-50">
                <td className="td font-mono"><Link className="text-accent-dark hover:underline" to={`/rfqs/${r.id}`}>{r.rfq_number}</Link></td>
                <td className="td">{r.item_name}<div className="text-xs text-stone-500">{r.material_text}</div></td>
                <td className="td num">{r.quantity} {r.unit}</td>
                <td className="td">{r.need_date || '—'}</td>
                <td className="td"><Badge map={RFQ_STATUS} value={r.status} /></td>
                <td className="td">
                  {r.latest_quote ? (
                    <Link to={`/quotes/${r.latest_quote.id}`} className="flex items-center gap-2 font-mono text-xs hover:underline">
                      {r.latest_quote.quote_no} r{r.latest_quote.quote_revision}
                      <Badge map={QUOTE_STATUS} value={r.latest_quote.status} />
                    </Link>
                  ) : '—'}
                </td>
                <td className="td text-xs text-stone-500">{dt(r.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
