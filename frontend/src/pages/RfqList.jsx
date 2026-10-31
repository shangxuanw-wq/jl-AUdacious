import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../api.js'
import { Arrow, Plus, Search, STAGE, shortTime } from '../ui.jsx'

const TABS = [
  ['all', '全部', null],
  ['todo', '待報價', ['todo', 'draft', 'failed']],
  ['review', '審核中', ['sending', 'review']],
  ['done', '完成', ['published', 'closed']],
]

const money = (v, cur = 'TWD') => (v === null || v === undefined ? '' : `${cur} ${Number(v).toLocaleString('zh-TW', { maximumFractionDigits: 2 })}`)

export default function RfqList({ cfg, me }) {
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [params, setParams] = useSearchParams()
  const tab = TABS.some(([k]) => k === params.get('tab')) ? params.get('tab') : 'all'
  const q = params.get('q') || ''

  useEffect(() => {
    api('/rfqs').then((d) => setRows(d.rfqs)).catch((e) => setError(e.message))
  }, [])

  const setParam = (k, v) => {
    const next = new URLSearchParams(params)
    if (v && !(k === 'tab' && v === 'all')) next.set(k, v)
    else next.delete(k)
    setParams(next, { replace: true })
  }

  const countOf = (k) => {
    const allow = TABS.find(([x]) => x === k)[2]
    return (rows || []).filter((r) => !allow || allow.includes(r.stage)).length
  }

  const shown = useMemo(() => {
    const allow = TABS.find(([k]) => k === tab)[2]
    const needle = q.trim().toLowerCase()
    return (rows || []).filter(
      (r) => (!allow || allow.includes(r.stage)) && (!needle || `${r.rfq_number} ${r.item_name} ${r.material_text}`.toLowerCase().includes(needle)),
    )
  }, [rows, tab, q])

  return (
    <div className="space-y-5">
      <div className="flex animate-rise flex-wrap items-end justify-between gap-3">
        <h1 className="text-[26px] font-black">詢價單</h1>
        {cfg?.manual_rfq_enabled && me?.role !== 'viewer' && <ManualCreate />}
      </div>

      {error && <p className="error">{error}</p>}

      <div className="flex animate-rise flex-wrap items-center gap-3" style={{ animationDelay: '.06s' }}>
        <div className="flex w-full gap-1 rounded-xl bg-stone-100 p-1 sm:inline-flex sm:w-auto" role="tablist">
          {TABS.map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={tab === k}
              onClick={() => setParam('tab', k)}
              className={`min-h-[36px] flex-1 whitespace-nowrap rounded-[9px] px-2 text-sm font-medium transition sm:flex-none sm:px-3.5 ${tab === k ? 'bg-white text-accent-dark shadow-sm' : 'text-stone-500 hover:text-stone-900'}`}
            >
              {label}
              {rows && <span className={`num ml-1.5 ${k === 'review' && countOf(k) > 0 ? 'text-accent' : 'text-stone-400'}`}>{countOf(k)}</span>}
            </button>
          ))}
        </div>
        <label className="relative w-full sm:ml-auto sm:max-w-[360px] sm:flex-[1_1_240px]">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-500"><Search /></span>
          <input
            type="search"
            className="input pl-9"
            placeholder="搜尋詢價編號、品名、材質"
            aria-label="搜尋詢價單"
            value={q}
            onChange={(e) => setParam('q', e.target.value)}
          />
        </label>
      </div>

      <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.12s' }}>
        {rows === null && !error && <div className="px-5 py-12 text-center text-sm text-stone-500">載入中…</div>}
        {rows && shown.length === 0 && (
          <div className="px-5 py-12 text-center text-sm text-stone-500">{rows.length === 0 ? '還沒有詢價單，收到詢價信會自動出現在這裡' : '沒有符合的詢價單'}</div>
        )}
        {shown.map((r) => (
          <Row key={r.id} r={r} />
        ))}
      </section>
    </div>
  )
}

function Row({ r }) {
  const st = STAGE[r.stage] || STAGE.todo
  const lq = r.latest_quote
  return (
    <Link to={`/rfqs/${r.id}`} className="group flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-stone-100 px-5 py-[18px] transition-colors first:border-t-0 hover:bg-[#FFFBF7]">
      <div className="min-w-0 flex-[1_1_280px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[15px] font-semibold">{r.rfq_number}</span>
          {r.is_test && <span className="chip-line">測試單</span>}
        </div>
        <div className="mt-1 truncate text-sm text-stone-700">{r.item_name}</div>
        <div className="mt-0.5 text-xs text-stone-500">
          {r.material_text}・{r.quantity} {r.unit}
          {r.need_date || r.need_date_text ? `・需求日 ${r.need_date || r.need_date_text}` : ''}
        </div>
      </div>
      <div className="min-w-[140px] flex-[0_1_180px]">
        <div className="flex items-center gap-1" aria-hidden="true">
          {[0, 1, 2, 3].map((i) => (
            <i key={i} className={`block h-1 w-[18px] rounded-sm ${i < st.done ? 'bg-accent' : i === st.done ? 'animate-ring bg-accent/50' : 'bg-stone-200'}`} />
          ))}
        </div>
        <div className={`mt-1.5 text-[13px] font-medium ${r.stage === 'failed' ? 'text-red-700' : st.done >= 4 ? 'text-stone-500' : 'text-accent'}`}>{st.label}</div>
      </div>
      <div className="min-w-[150px] flex-[0_1_200px]">
        {lq ? (
          <>
            <div className="font-mono text-[13px] text-stone-500">{lq.quote_no} r{lq.quote_revision}</div>
            <div className="num text-lg font-bold">{money(lq.grand_total, lq.currency)}</div>
          </>
        ) : (
          <div className="text-[13px] text-stone-400">還沒報價</div>
        )}
      </div>
      <div className="min-w-[90px] text-xs text-stone-500">{shortTime(r.created_at)}</div>
      <span className="text-stone-400 transition duration-200 group-hover:translate-x-1 group-hover:text-accent"><Arrow /></span>
    </Link>
  )
}

const EMPTY = { rfq_number: 'AUD-RFQ-2026-', item_name: '', material_text: '', quantity: 1, unit: 'pcs', need_date: '', sync_mock: true }

/** 只在 MANUAL_RFQ_ENABLED=true（開發測試）時出現。 */
function ManualCreate() {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [error, setError] = useState('')
  const nav = useNavigate()
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const submit = async (e) => {
    e.preventDefault()
    try {
      const r = await api('/rfqs', { method: 'POST', body: { ...form, quantity: Number(form.quantity), need_date: form.need_date || null } })
      nav(`/rfqs/${r.id}`)
    } catch (err) {
      setError(err.message)
    }
  }
  if (!open)
    return (
      <button className="btn-ghost btn-sm" onClick={() => setOpen(true)}>
        <Plus size={14} />
        手動建立（測試）
      </button>
    )
  return (
    <form onSubmit={submit} className="card grid w-full animate-drop gap-3 p-5 sm:grid-cols-6">
      <div className="sm:col-span-2"><label className="label" htmlFor="m-no">詢價編號</label><input id="m-no" className="input font-mono" value={form.rfq_number} onChange={set('rfq_number')} required /></div>
      <div className="sm:col-span-4"><label className="label" htmlFor="m-item">品名</label><input id="m-item" className="input" value={form.item_name} onChange={set('item_name')} required /></div>
      <div className="sm:col-span-2"><label className="label" htmlFor="m-mat">材質</label><input id="m-mat" className="input" value={form.material_text} onChange={set('material_text')} required /></div>
      <div><label className="label" htmlFor="m-qty">數量</label><input id="m-qty" className="input num" type="number" min="1" value={form.quantity} onChange={set('quantity')} required /></div>
      <div><label className="label" htmlFor="m-unit">單位</label><select id="m-unit" className="input" value={form.unit} onChange={set('unit')}><option value="pcs">pcs</option><option value="sets">sets</option></select></div>
      <div className="sm:col-span-2"><label className="label" htmlFor="m-need">需求日</label><input id="m-need" className="input" type="date" value={form.need_date} onChange={set('need_date')} /></div>
      <label className="flex items-center gap-2 text-sm text-stone-600 sm:col-span-4"><input type="checkbox" checked={form.sync_mock} onChange={set('sync_mock')} />同時建在模擬對方</label>
      <div className="flex justify-end gap-2 sm:col-span-2">
        <button type="button" className="btn-ghost" onClick={() => setOpen(false)}>取消</button>
        <button className="btn-primary">建立</button>
      </div>
      {error && <p className="error sm:col-span-6">{error}</p>}
    </form>
  )
}
