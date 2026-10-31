import { useMemo, useState } from 'react'
import { money } from '../api.js'

function addDays(iso, n) {
  const d = new Date(iso + 'T00:00:00')
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

// 跟後端同一套算法：以「分」計算，台幣稅額四捨五入到元
export function computeTotals(unitPrice, qty, taxIncluded, taxRate = 0.05) {
  const cents = Math.round(Number(unitPrice || 0) * 100) * Number(qty || 0)
  const tax = taxIncluded ? null : Math.round((cents * taxRate) / 100) * 100
  return { subtotal: cents / 100, total: cents / 100, tax: tax === null ? null : tax / 100, grand: (cents + (tax || 0)) / 100 }
}

export default function QuoteForm({ rfq, initial, today, submitLabel, onSubmit, onCancel }) {
  const item = initial?.items?.[0]
  const [f, setF] = useState({
    unit_price: item ? String(item.unit_price) : '',
    lead_days: item ? String(item.lead_days) : '10',
    qty: item ? String(item.qty) : String(rfq.quantity),
    unit: item ? item.unit : rfq.unit,
    part: item ? item.part : rfq.item_name,
    material: item ? item.material : rfq.material_text,
    valid_until: initial?.valid_until || addDays(today, 28),
    tax_included: initial ? initial.tax_included : false,
    lead_basis: initial?.lead_basis || 'po',
    delivery_date: initial?.delivery_date || '',
    note: initial?.note || '',
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = (k) => (e) => setF((x) => ({ ...x, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }))
  const t = useMemo(() => computeTotals(f.unit_price, f.qty, f.tax_included), [f.unit_price, f.qty, f.tax_included])
  const mismatch = f.part !== rfq.item_name || f.material !== rfq.material_text || Number(f.qty) !== rfq.quantity || f.unit !== rfq.unit

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      await onSubmit({
        unit_price: f.unit_price,
        lead_days: Number(f.lead_days),
        qty: Number(f.qty),
        unit: f.unit,
        part: f.part,
        material: f.material,
        valid_until: f.valid_until,
        tax_included: f.tax_included,
        lead_basis: f.lead_basis,
        delivery_date: f.delivery_date || null,
        clear_delivery_date: !f.delivery_date,
        note: f.note,
      })
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="card space-y-4 border-accent p-5 ring-4 ring-accent/10">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-[17px] font-bold">{initial ? `報價 ${initial.quote_no}` : '新報價'}</h2>
        <span className="text-xs text-stone-500">品名、材質已帶入詢價信原文</span>
      </div>
      <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-6">
        <div className="col-span-2">
          <label className="label" htmlFor="qf-price">單價（TWD，未稅）</label>
          <input id="qf-price" className="input num" inputMode="decimal" value={f.unit_price} onChange={set('unit_price')} required placeholder="350" pattern="^\d+(\.\d{1,2})?$" title="最多兩位小數" autoFocus={!initial} />
        </div>
        <div>
          <label className="label" htmlFor="qf-qty">數量</label>
          <input id="qf-qty" className="input num" type="number" min="1" value={f.qty} onChange={set('qty')} required />
        </div>
        <div>
          <label className="label" htmlFor="qf-unit">單位</label>
          <select id="qf-unit" className="input" value={f.unit} onChange={set('unit')}>
            <option value="pcs">pcs</option>
            <option value="sets">sets</option>
          </select>
        </div>
        <div>
          <label className="label" htmlFor="qf-lead">交期（工作天）</label>
          <input id="qf-lead" className="input num" type="number" min="0" max="365" value={f.lead_days} onChange={set('lead_days')} required />
        </div>
        <div>
          <label className="label" htmlFor="qf-basis">起算</label>
          <select id="qf-basis" className="input" value={f.lead_basis} onChange={set('lead_basis')}>
            <option value="po">收到 PO</option>
            <option value="quote">報價日</option>
          </select>
        </div>
        <div className="col-span-2 sm:col-span-3">
          <label className="label" htmlFor="qf-part">品名（要跟詢價信一字不差）</label>
          <input id="qf-part" className="input" value={f.part} onChange={set('part')} required />
        </div>
        <div className="col-span-2 sm:col-span-3">
          <label className="label" htmlFor="qf-mat">材質（要跟詢價信一字不差）</label>
          <input id="qf-mat" className="input" value={f.material} onChange={set('material')} required />
        </div>
        <div className="col-span-2 sm:col-span-2">
          <label className="label" htmlFor="qf-valid">報價有效期</label>
          <input id="qf-valid" className="input" type="date" value={f.valid_until} onChange={set('valid_until')} required min={today} />
        </div>
        <div className="col-span-2 sm:col-span-2">
          <label className="label" htmlFor="qf-deliv">承諾交貨日（可空白）</label>
          <input id="qf-deliv" className="input" type="date" value={f.delivery_date} onChange={set('delivery_date')} min={today} />
        </div>
        <label className="col-span-2 flex min-h-[44px] items-end gap-2 pb-2.5 text-sm text-stone-700">
          <input type="checkbox" className="h-5 w-5 accent-[#C2410C]" checked={f.tax_included} onChange={set('tax_included')} />
          合計已含稅
        </label>
        <div className="col-span-2 sm:col-span-6">
          <label className="label" htmlFor="qf-note">備註（對方看得到；不要寫協力廠商名稱或成本）</label>
          <textarea id="qf-note" className="input" rows={2} maxLength={1000} value={f.note} onChange={set('note')} />
        </div>
      </div>

      {mismatch && <p className="notice">品名、材質、數量或單位跟詢價單不同，對方會收下但標成「待審」。</p>}

      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-xl bg-stone-50 px-4 py-3.5">
        <div className="text-sm text-stone-500">小計 <b className="num text-stone-900">{money(t.subtotal)}</b></div>
        <div className="text-sm text-stone-500">營業稅 5% <b className="num text-stone-900">{t.tax === null ? '（已含）' : money(t.tax)}</b></div>
        <div className="text-sm text-stone-500 sm:ml-auto">含稅合計 <b className="num text-[22px] text-accent">{money(t.grand)}</b></div>
      </div>
      <div className="flex justify-end gap-2.5">
        {onCancel && <button type="button" className="btn-ghost" onClick={onCancel}>取消</button>}
        <button className="btn-primary" disabled={busy}>{busy ? '處理中…' : submitLabel}</button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
