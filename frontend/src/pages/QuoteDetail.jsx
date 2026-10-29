import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, dt, money } from '../api.js'
import { Badge, DISPATCH_STATUS, MAIL_STATUS, QUOTE_STATUS, issueText } from '../labels.jsx'
import QuoteForm from './QuoteForm.jsx'

const ACTIVE = new Set(['pending', 'sending', 'retry_wait'])

export default function QuoteDetail({ cfg }) {
  const { id } = useParams()
  const nav = useNavigate()
  const [q, setQ] = useState(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState(null) // 'edit' | 'revise'
  const [busy, setBusy] = useState(false)
  const [showJson, setShowJson] = useState(false)

  const load = useCallback(() => api(`/quotes/${id}`).then(setQ).catch((e) => setError(e.message)), [id])
  useEffect(() => { setMode(null); load() }, [load])

  const active = q?.dispatches?.some((d) => ACTIVE.has(d.status))
  useEffect(() => {
    if (!active) return
    // 佇列沒推送時的備援：順便請後端處理到期的重送
    const t = setInterval(() => api('/dispatches/sweep', { method: 'POST' }).catch(() => {}).finally(load), 5000)
    return () => clearInterval(t)
  }, [active, load])

  if (error && !q) return <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
  if (!q) return <p className="text-sm text-stone-500">載入中…</p>
  const item = q.items[0]
  const latestRev = Math.max(...q.revisions.map((r) => r.quote_revision))
  const isLatest = q.quote_revision === latestRev
  const today = cfg?.today || new Date().toISOString().slice(0, 10)

  const doSend = async () => {
    const target = cfg?.target_is_partner_prod ? '澳得仕正式站' : '假澳得仕'
    const mailTo = !q.has_source_mail ? '（手動建立的詢價單沒有原信，不寄回信）' : q.reply_mode === 'live' ? `，並回信附 PDF 給承辦人 ${q.rfq.reply_to}` : q.reply_mode === 'self' ? '，回信附 PDF 只寄給我方信箱（開發期）' : '（回信已關閉）'
    if (!window.confirm(`確定送出 ${q.quote_no} r${q.quote_revision} 到「${target}」${mailTo}？`)) return
    setBusy(true)
    setError('')
    try {
      await api(`/quotes/${id}/send`, { method: 'POST' })
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const requeue = async (did) => {
    setBusy(true)
    try {
      await api(`/dispatches/${did}/requeue`, { method: 'POST' })
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const resendMail = async () => {
    if (!window.confirm(q.reply_mode === 'live' ? `重寄回信（附 PDF）給 ${q.rfq.reply_to}？` : '重寄回信（附 PDF）？')) return
    setBusy(true)
    try {
      const r = await api(`/quotes/${id}/mail`, { method: 'POST' })
      if (r.status === 'skipped') setError(`沒有寄：${r.reason}`)
      await load()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = async (body) => {
    const r = await api(`/quotes/${id}`, { method: 'PUT', body })
    setQ(r)
    setMode(null)
  }
  const saveRevise = async (body) => {
    const r = await api(`/quotes/${id}/revise`, { method: 'POST', body })
    nav(`/quotes/${r.id}`)
  }

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/rfqs/${q.rfq_id}`} className="text-sm text-stone-500 hover:underline">← {q.rfq.rfq_number}</Link>
        <div className="mt-1 flex flex-wrap items-center gap-3">
          <h1 className="font-mono text-xl font-bold">{q.quote_no}</h1>
          <span className="rounded-md bg-stone-200 px-2 py-0.5 font-mono text-xs">r{q.quote_revision}</span>
          <Badge map={QUOTE_STATUS} value={q.status} />
          <span className="rounded-md bg-sky-50 px-2 py-0.5 text-xs text-sky-700 ring-1 ring-sky-200">規格版次 {q.rfq_revision ?? '—'}</span>
          <div className="ml-auto flex flex-wrap gap-2">
            <a className="btn-ghost" href={`/api/quotes/${id}/pdf`} target="_blank" rel="noreferrer">報價單 PDF</a>
            {q.status === 'draft' && mode === null && <button className="btn-ghost" onClick={() => setMode('edit')}>修改草稿</button>}
            {['draft', 'failed'].includes(q.status) && mode === null && (
              <button className="btn-primary" onClick={doSend} disabled={busy || !q.payload_preview}>{busy ? '送出中…' : '送出報價'}</button>
            )}
            {isLatest && ['sent', 'failed'].includes(q.status) && mode === null && (
              <button className="btn-ghost" onClick={() => setMode('revise')}>修訂（r{q.quote_revision + 1}）</button>
            )}
          </div>
        </div>
        {q.revisions.length > 1 && (
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            {q.revisions.map((r) => (
              <Link key={r.id} to={`/quotes/${r.id}`} className={`rounded-full px-2 py-0.5 ring-1 ${r.id === q.id ? 'bg-stone-900 text-white ring-stone-900' : 'ring-stone-300 hover:bg-stone-100'}`}>
                r{r.quote_revision}・{QUOTE_STATUS[r.status]?.[0] || r.status}
              </Link>
            ))}
          </div>
        )}
      </div>

      {error && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {mode === 'edit' && <QuoteForm rfq={q.rfq} initial={q} today={today} submitLabel="儲存草稿" onSubmit={saveEdit} onCancel={() => setMode(null)} />}
      {mode === 'revise' && (
        <>
          <p className="text-sm text-stone-600">修訂會建立 r{q.quote_revision + 1}（同一個報價單號），送出時 <code>quote_revision</code> 是 {q.quote_revision + 1}、用新的 event_id。</p>
          <QuoteForm rfq={q.rfq} initial={q} today={today} submitLabel={`建立 r${q.quote_revision + 1} 草稿`} onSubmit={saveRevise} onCancel={() => setMode(null)} />
        </>
      )}

      {mode === null && (
        <section className="card grid gap-4 p-5 sm:grid-cols-4">
          <Field label="品名" value={item.part} wide />
          <Field label="材質" value={item.material} />
          <Field label="數量" value={`${item.qty} ${item.unit}`} />
          <Field label="單價" value={money(item.unit_price, q.currency)} />
          <Field label="小計" value={money(q.totals?.subtotal, q.currency)} />
          <Field label="營業稅" value={q.tax_included ? '已含在合計' : money(q.totals?.tax, q.currency)} />
          <Field label="含稅合計" value={money(q.totals?.grand_total, q.currency)} strong />
          <Field label="交期" value={`${item.lead_days} 個工作天（自${q.lead_basis === 'po' ? '收到 PO' : '報價日'}起算）`} wide />
          <Field label="報價日" value={q.quote_date} />
          <Field label="有效期" value={q.valid_until} />
          <Field label="承諾交貨日" value={q.delivery_date || '—'} />
          <Field label="備註" value={q.note || '—'} wide />
          {q.warnings?.length > 0 && (
            <div className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800 sm:col-span-4">
              跟詢價單不同：{q.warnings.map(issueText).join('、')}（澳得仕會標成待審）
            </div>
          )}
        </section>
      )}

      {q.status !== 'draft' && (
        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <h2 className="font-bold">回信（附報價單 PDF）</h2>
            {q.has_source_mail && q.reply_mode !== 'off' && (
              <button className="btn-ghost px-2.5 py-1 text-xs" onClick={resendMail} disabled={busy}>重寄回信</button>
            )}
          </div>
          {!q.has_source_mail && <p className="text-sm text-stone-500">這張詢價單是手動建立的，沒有原信可以回覆。</p>}
          {q.has_source_mail && q.mails.length === 0 && <p className="text-sm text-stone-500">還沒寄。</p>}
          {q.mails.map((m) => (
            <div key={m.id} className="card flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
              <Badge map={MAIL_STATUS} value={m.status} />
              <span className="text-xs text-stone-500">{m.mode === 'self' ? '只寄給自己（開發期）' : '寄給承辦人'}</span>
              <span className="font-mono text-xs">{m.to_addr}</span>
              <span className="text-xs text-stone-500">{dt(m.sent_at || m.created_at)}</span>
              {m.error && <span className="text-xs text-red-700">{m.error}</span>}
            </div>
          ))}
        </section>
      )}

      <section className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-bold">送出紀錄</h2>
          <button className="text-xs text-stone-500 hover:underline" onClick={() => setShowJson((v) => !v)}>{showJson ? '隱藏' : '看'}送出的 JSON</button>
        </div>
        {showJson && (
          <pre className="card max-h-96 overflow-auto p-4 font-mono text-xs leading-relaxed">
            {JSON.stringify(q.dispatches[0]?.payload || q.payload_preview, null, 2)}
          </pre>
        )}
        {q.dispatches.length === 0 && <p className="text-sm text-stone-500">還沒送出。</p>}
        {q.dispatches.map((d) => (
          <div key={d.id} className="card p-4">
            <div className="flex flex-wrap items-center gap-3">
              <Badge map={DISPATCH_STATUS} value={d.status} />
              <span className="font-mono text-xs text-stone-500">{d.event_id}</span>
              <span className="text-xs text-stone-500">嘗試 {d.attempt_count}／7</span>
              {d.status === 'retry_wait' && <span className="text-xs text-amber-700">下次：{dt(d.next_attempt_at)}</span>}
              {ACTIVE.has(d.status) && (
                <button className="btn-ghost ml-auto px-2.5 py-1 text-xs" onClick={() => requeue(d.id)} disabled={busy}>立即重送</button>
              )}
            </div>
            {d.last_error_code && <p className="mt-2 text-sm text-stone-700">原因：{issueText(d.last_error_code)}</p>}
            {d.last_response?.issues?.length > 0 && (
              <ul className="mt-2 list-disc space-y-0.5 pl-5 text-sm text-amber-800">
                {d.last_response.issues.map((i, n) => <li key={n}>{issueText(i.code)}：{i.message}</li>)}
              </ul>
            )}
            {d.candidate_id && <p className="mt-2 text-xs text-stone-500">對方候選：<span className="font-mono">{d.candidate_id}</span>（第 {d.candidate_revision} 版）</p>}
            <table className="mt-3 w-full">
              <thead>
                <tr>
                  <th className="th">#</th>
                  <th className="th">時間</th>
                  <th className="th">HTTP</th>
                  <th className="th">結果</th>
                  <th className="th">request_id</th>
                </tr>
              </thead>
              <tbody>
                {d.attempts.map((a) => (
                  <tr key={a.id}>
                    <td className="td num">{a.attempt_no}</td>
                    <td className="td text-xs">{dt(a.started_at)}</td>
                    <td className="td num">{a.http_status ?? '—'}</td>
                    <td className="td text-xs">{a.error ? issueText(a.error) : 'OK'}</td>
                    <td className="td font-mono text-xs">{a.request_id}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
      </section>
    </div>
  )
}

function Field({ label, value, wide, strong }) {
  return (
    <div className={wide ? 'sm:col-span-2' : ''}>
      <div className="label">{label}</div>
      <div className={`text-sm ${strong ? 'font-bold' : ''}`}>{value}</div>
    </div>
  )
}
