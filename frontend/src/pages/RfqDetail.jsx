import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, money } from '../api.js'
import { Badge, DISPATCH_STATUS, QUOTE_STATUS, RFQ_STATUS } from '../labels.jsx'
import QuoteForm from './QuoteForm.jsx'

export default function RfqDetail({ cfg }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const nav = useNavigate()

  useEffect(() => {
    api(`/rfqs/${id}`).then(setData).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
  if (!data) return <p className="text-sm text-stone-500">載入中…</p>
  const { rfq, quotes } = data
  const today = cfg?.today || new Date().toISOString().slice(0, 10)

  const create = async (body) => {
    const q = await api(`/rfqs/${id}/quotes`, { method: 'POST', body })
    nav(`/quotes/${q.id}`)
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to="/" className="text-sm text-stone-500 hover:underline">← 詢價單</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-xl font-bold">{rfq.rfq_number}</h1>
          <Badge map={RFQ_STATUS} value={rfq.status} />
          <span className="rounded-md bg-sky-50 px-2 py-0.5 text-xs text-sky-700 ring-1 ring-sky-200">規格版次 {rfq.spec_revision}</span>
          {rfq.is_test && <span className="rounded-md bg-violet-50 px-2 py-0.5 text-xs text-violet-700 ring-1 ring-violet-200">測試單</span>}
          {!data.in_mock && cfg && !cfg.target_is_partner_prod && (
            <span className="text-xs text-amber-700">假澳得仕沒有這張詢價單，送出會回 404</span>
          )}
        </div>
      </div>

      {quotes.length > 0 && quotes.every((q) => (q.rfq_revision || 0) < rfq.spec_revision) && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">規格已改到第 {rfq.spec_revision} 版，現有報價都是舊版規格，請照新版重新報價。</p>
      )}
      <section className="card grid gap-4 p-5 sm:grid-cols-4">
        <Field label="品名" value={rfq.item_name} wide />
        <Field label="材質" value={rfq.material_text} />
        <Field label="數量" value={`${rfq.quantity} ${rfq.unit}`} />
        <Field label="需求日" value={rfq.need_date || rfq.need_date_text || '請報交期'} />
        <Field label="來源" value={rfq.source === 'email' ? `詢價信（${rfq.mail_count} 封）` : '手動建立'} />
        <Field label="聯絡人" value={rfq.contact_name ? `${rfq.contact_name}${rfq.contact_email ? ` <${rfq.contact_email}>` : ''}` : '—'} wide />
        <Field label="回覆給（Reply-To）" value={rfq.reply_to || '—'} />
        <Field label="建立者" value={rfq.created_by === 'mail' ? '系統（收信）' : rfq.created_by || '—'} />
      </section>

      {(rfq.spec_text || data.attachments?.length > 0) && (
        <section className="card grid gap-4 p-5 sm:grid-cols-3">
          <div className="sm:col-span-2">
            <div className="label">規格與備註</div>
            <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed">{rfq.spec_text || '—'}</pre>
          </div>
          <div>
            <div className="label">附件（最新一封信）</div>
            {data.attachments.length === 0 && <p className="text-sm text-stone-500">無</p>}
            <ul className="space-y-1 text-sm">
              {data.attachments.map((a) => (
                <li key={a.n}>
                  <a className="text-accent-dark hover:underline" href={`/api/rfqs/${rfq.id}/attachments/${a.n}`}>{a.filename}</a>
                  <span className="ml-1 text-xs text-stone-500">{a.size ? `${Math.max(1, Math.round(a.size / 1024))} KB` : ''}</span>
                </li>
              ))}
            </ul>
          </div>
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-bold">報價</h2>
          {!creating && rfq.status !== 'closed' && (
            <button className="btn-primary" onClick={() => setCreating(true)}>＋ 建立報價</button>
          )}
        </div>
        {creating && <QuoteForm rfq={rfq} today={today} submitLabel="建立草稿" onSubmit={create} onCancel={() => setCreating(false)} />}
        {quotes.length === 0 && !creating && <p className="text-sm text-stone-500">還沒有報價。</p>}
        {quotes.length > 0 && (
          <div className="card overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="bg-stone-50">
                <tr>
                  <th className="th">報價單號</th>
                  <th className="th">版次</th>
                  <th className="th">單價 × 數量</th>
                  <th className="th">含稅合計</th>
                  <th className="th">交期</th>
                  <th className="th">狀態</th>
                  <th className="th">送出結果</th>
                </tr>
              </thead>
              <tbody>
                {quotes.map((q) => (
                  <tr key={q.id} className="hover:bg-stone-50">
                    <td className="td font-mono"><Link className="text-accent-dark hover:underline" to={`/quotes/${q.id}`}>{q.quote_no}</Link></td>
                    <td className="td num">r{q.quote_revision}</td>
                    <td className="td num">{money(q.items[0]?.unit_price)} × {q.items[0]?.qty}</td>
                    <td className="td num">{money(q.totals?.grand_total)}</td>
                    <td className="td num">{q.items[0]?.lead_days} 天</td>
                    <td className="td"><Badge map={QUOTE_STATUS} value={q.status} /></td>
                    <td className="td">{q.latest_dispatch ? <Badge map={DISPATCH_STATUS} value={q.latest_dispatch.status} /> : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function Field({ label, value, wide }) {
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <div className="label">{label}</div>
      <div className="text-sm">{value}</div>
    </div>
  )
}
