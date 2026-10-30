import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, dt, money } from '../api.js'
import { DISPATCH_STATUS, QUOTE_STATUS, issueText } from '../labels.jsx'
import { Alert, Check, Chevron, Clock, Doc, STAGE, Stepper, shortTime, stageOf } from '../ui.jsx'
import QuoteForm from './QuoteForm.jsx'

const ACTIVE = new Set(['pending', 'sending', 'retry_wait'])
const OK = new Set(['accepted', 'duplicate', 'published'])

export default function QuoteDetail({ cfg, me }) {
  const { id } = useParams()
  const nav = useNavigate()
  const [q, setQ] = useState(null)
  const [error, setError] = useState('')
  const [mode, setMode] = useState(null) // 'edit' | 'revise'
  const [busy, setBusy] = useState(false)
  const [tech, setTech] = useState(false)
  const [showJson, setShowJson] = useState(false)

  const load = useCallback(() => api(`/quotes/${id}`).then(setQ).catch((e) => setError(e.message)), [id])
  useEffect(() => {
    setMode(null)
    load()
  }, [load])

  const canEdit = me?.role !== 'viewer'
  const active = q?.dispatches?.some((d) => ACTIVE.has(d.status))
  useEffect(() => {
    if (!active) return
    // 佇列沒推送時的備援：順便請後端處理到期的重送
    const t = setInterval(() => (canEdit ? api('/dispatches/sweep', { method: 'POST' }).catch(() => {}) : Promise.resolve()).finally(load), 5000)
    return () => clearInterval(t)
  }, [active, load, canEdit])

  if (error && !q) return <p className="error">{error}</p>
  if (!q) return <p className="text-sm text-stone-500">載入中…</p>
  const item = q.items[0]
  const latestRev = Math.max(...q.revisions.map((r) => r.quote_revision))
  const isLatest = q.quote_revision === latestRev
  const today = cfg?.today || new Date().toISOString().slice(0, 10)
  const d = q.dispatches[0]
  const mail = q.mails[0]
  const stage = stageOf(q.rfq.status, q.status, d?.status)
  const st = STAGE[stage]

  const run = async (fn) => {
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

  const doSend = () => {
    const target = cfg?.target_is_partner_prod ? '對方正式系統' : '模擬環境'
    const mailTo = !q.has_source_mail
      ? '（手動建立的詢價單沒有原信，不寄回信）'
      : q.reply_mode === 'live'
        ? `，並回信附 PDF 給 ${q.rfq.reply_to}`
        : q.reply_mode === 'self'
          ? '，回信附 PDF 只寄給我方信箱'
          : '（回信已關閉）'
    if (!window.confirm(`確定送出 ${q.quote_no} r${q.quote_revision} 到${target}${mailTo}？`)) return
    run(() => api(`/quotes/${id}/send`, { method: 'POST' }))
  }
  const resendMail = () => {
    if (!window.confirm(q.reply_mode === 'live' ? `重寄回信（附 PDF）給 ${q.rfq.reply_to}？` : '重寄回信（附 PDF）？')) return
    run(async () => {
      const r = await api(`/quotes/${id}/mail`, { method: 'POST' })
      if (r.status === 'skipped') throw new Error(`沒有寄：${r.reason}`)
    })
  }
  const saveEdit = async (body) => {
    setQ(await api(`/quotes/${id}`, { method: 'PUT', body }))
    setMode(null)
  }
  const saveRevise = async (body) => {
    const r = await api(`/quotes/${id}/revise`, { method: 'POST', body })
    nav(`/quotes/${r.id}`)
  }

  const steps = [
    { label: '建立草稿', sub: shortTime(q.created_at) },
    { label: '送出＋回信', sub: d ? shortTime(d.created_at) : '' },
    { label: '審核中', sub: stage === 'review' ? 'PDF 與 JSON 核對' : '' },
    { label: '完成', sub: stage === 'published' ? '對方已發布' : '' },
  ]

  return (
    <div className="space-y-5">
      <div className="flex animate-rise flex-wrap items-end gap-4">
        <div className="min-w-0 flex-[1_1_420px]">
          <div className="text-[13px] text-stone-500">
            <Link to="/" className="hover:text-stone-900">詢價單</Link> ／{' '}
            <Link to={`/rfqs/${q.rfq_id}`} className="font-mono hover:text-stone-900">{q.rfq.rfq_number}</Link> ／
          </div>
          <div className="mb-2.5 mt-1.5 flex flex-wrap items-baseline gap-2.5">
            <h1 className="font-mono text-[28px] font-semibold tracking-tight">{q.quote_no}</h1>
            <span className="font-mono text-base text-stone-500">r{q.quote_revision}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={q.status === 'superseded' ? 'chip-mute' : st.chip}>{q.status === 'superseded' ? QUOTE_STATUS.superseded[0] : st.label}</span>
            <span className="chip-mute">規格版次 {q.rfq_revision ?? '—'}</span>
            <span className="chip-mute">{item?.part}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <a className="btn-ghost" href={`/api/quotes/${id}/pdf`} target="_blank" rel="noreferrer"><Doc />報價單 PDF</a>
          {canEdit && q.status === 'draft' && mode === null && <button className="btn-ghost" onClick={() => setMode('edit')}>修改草稿</button>}
          {canEdit && ['draft', 'failed'].includes(q.status) && mode === null && (
            <button className="btn-primary" onClick={doSend} disabled={busy || !q.payload_preview}>{busy ? '送出中…' : '送出報價'}</button>
          )}
          {canEdit && isLatest && ['sent', 'failed'].includes(q.status) && mode === null && (
            <button className={q.status === 'sent' ? 'btn-primary' : 'btn-ghost'} onClick={() => setMode('revise')}>修訂成 r{q.quote_revision + 1}</button>
          )}
        </div>
      </div>

      {q.status !== 'superseded' && <Stepper steps={steps} done={st.done} style={{ animationDelay: '.06s' }} />}

      {error && <p className="error">{error}</p>}
      {q.payload_error && q.status === 'draft' && <p className="error">還不能送出：{q.payload_error}</p>}

      {mode === 'edit' && (
        <div className="animate-drop"><QuoteForm rfq={q.rfq} initial={q} today={today} submitLabel="儲存草稿" onSubmit={saveEdit} onCancel={() => setMode(null)} /></div>
      )}
      {mode === 'revise' && (
        <div className="animate-drop space-y-2">
          <p className="text-sm text-stone-600">修訂會建立 r{q.quote_revision + 1}（同一個報價單號），送出時用新的 event_id。</p>
          <QuoteForm rfq={q.rfq} initial={q} today={today} submitLabel={`建立 r${q.quote_revision + 1} 草稿`} onSubmit={saveRevise} onCancel={() => setMode(null)} />
        </div>
      )}

      {mode === null && (
        <div className="flex flex-wrap items-start gap-5">
          <section className="card min-w-0 flex-[999_1_560px] animate-rise p-6" style={{ animationDelay: '.12s' }}>
            <div className="label">含稅合計</div>
            <div className="num animate-rise text-[44px] font-black leading-tight tracking-tight" style={{ animationDelay: '.2s' }}>{money(q.totals?.grand_total, q.currency)}</div>
            <div className="mt-1.5 text-sm text-stone-500">
              單價 {money(item?.unit_price, q.currency)} × {item?.qty} {item?.unit}・{q.tax_included ? '稅已含在合計' : `未稅 ${money(q.totals?.subtotal, q.currency)}＋營業稅 ${money(q.totals?.tax, q.currency)}`}
            </div>
            <dl className="m-0 mt-5">
              <div className="kv"><dt>品名</dt><dd>{item?.part}</dd></div>
              <div className="kv"><dt>材質</dt><dd>{item?.material}</dd></div>
              <div className="kv"><dt>交期</dt><dd>{item?.lead_days} 個工作天（自{q.lead_basis === 'po' ? '收到 PO' : '報價日'}起算）</dd></div>
              <div className="kv"><dt>報價日</dt><dd className="num">{q.quote_date}</dd></div>
              <div className="kv"><dt>有效期限</dt><dd className="num">{q.valid_until}</dd></div>
              <div className="kv"><dt>承諾交貨日</dt><dd className="num">{q.delivery_date || '—'}</dd></div>
              <div className="kv"><dt>備註</dt><dd className="whitespace-pre-wrap">{q.note || '—'}</dd></div>
            </dl>
            {q.warnings?.length > 0 && <p className="notice mt-4">跟詢價單不同：{q.warnings.map(issueText).join('、')}（對方會標成待審）</p>}
            {q.revisions.length > 0 && (
              <div className="mt-4 flex flex-wrap items-center gap-2">
                <span className="mr-1 text-xs text-stone-500">版本</span>
                {q.revisions.map((r) => (
                  <Link
                    key={r.id}
                    to={`/quotes/${r.id}`}
                    className={`inline-flex min-h-[32px] items-center rounded-full border px-3 text-[13px] transition ${r.id === q.id ? 'border-stone-900 bg-stone-900 text-white' : 'border-stone-300 text-stone-600 hover:bg-stone-100'}`}
                  >
                    r{r.quote_revision}・{QUOTE_STATUS[r.status]?.[0] || r.status}
                  </Link>
                ))}
              </div>
            )}
          </section>

          <aside className="flex min-w-0 flex-[1_1_340px] flex-col gap-5 2xl:flex-[1_1_420px]">
            <section className="card animate-rise p-5" style={{ animationDelay: '.18s' }}>
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="text-base font-bold">回信</h2>
                {canEdit && q.status !== 'draft' && q.has_source_mail && q.reply_mode !== 'off' && (
                  <button className="btn-ghost btn-sm" onClick={resendMail} disabled={busy}>{mail ? '重寄' : '寄出'}</button>
                )}
              </div>
              <StatusLine
                tone={!mail ? 'idle' : mail.status === 'sent' ? 'ok' : mail.status === 'failed' ? 'bad' : 'wait'}
                title={
                  q.status === 'draft'
                    ? '送出報價時會一起回信'
                    : !q.has_source_mail
                      ? '手動建立的詢價單，沒有原信可以回覆'
                      : !mail
                        ? '還沒寄'
                        : mail.status === 'sent'
                          ? `已寄${mail.mode === 'self' ? '給我方信箱' : '給承辦人'}（附 PDF）`
                          : mail.status === 'failed'
                            ? '寄送失敗'
                            : '寄送中'
                }
                sub={mail ? `${mail.to_addr}・${shortTime(mail.sent_at || mail.created_at)}${mail.error ? `・${mail.error}` : ''}` : ''}
              />
            </section>

            <section className="card animate-rise p-5" style={{ animationDelay: '.24s' }}>
              <div className="mb-3 flex items-center justify-between gap-2">
                <h2 className="text-base font-bold">對方系統</h2>
                {canEdit && d && ACTIVE.has(d.status) && (
                  <button className="btn-ghost btn-sm" onClick={() => run(() => api(`/dispatches/${d.id}/requeue`, { method: 'POST' }))} disabled={busy}>立即重送</button>
                )}
              </div>
              <StatusLine
                tone={!d ? 'idle' : OK.has(d.status) ? 'ok-wait' : ACTIVE.has(d.status) ? 'wait' : 'bad'}
                title={!d ? '還沒送出' : d.status === 'accepted' || d.status === 'duplicate' ? '已收下，等待審核' : DISPATCH_STATUS[d.status]?.[0] || d.status}
                sub={
                  !d
                    ? ''
                    : d.status === 'retry_wait'
                      ? `第 ${d.attempt_count} 次沒成功，${shortTime(d.next_attempt_at)} 自動再試`
                      : `${d.attempt_count === 1 ? '第 1 次就送達' : `共試 ${d.attempt_count} 次`}・${shortTime(d.updated_at || d.created_at)}`
                }
              />
              {d?.last_error_code && !OK.has(d.status) && <p className="mt-3 text-sm text-stone-700">原因：{issueText(d.last_error_code)}</p>}
              {d?.last_response?.issues?.length > 0 && (
                <ul className="mt-3 list-disc space-y-0.5 pl-5 text-sm text-accent-dark">
                  {d.last_response.issues.map((i, n) => <li key={n}>{issueText(i.code)}{i.message ? `：${i.message}` : ''}</li>)}
                </ul>
              )}
              {(d || q.payload_preview) && (
                <div className="mt-3 border-t border-stone-100">
                  <button className="flex min-h-[44px] w-full items-center justify-between text-sm font-medium text-stone-500 hover:text-stone-900" onClick={() => setTech((v) => !v)} aria-expanded={tech}>
                    技術細節
                    <Chevron className={`transition-transform duration-200 ${tech ? 'rotate-180' : ''}`} />
                  </button>
                  {tech && (
                    <div className="flex animate-drop flex-col gap-2.5 text-[13px]">
                      {d && (
                        <>
                          <div><div className="label">event_id</div><div className="break-all font-mono">{d.event_id}</div></div>
                          {d.candidate_id && <div><div className="label">對方候選 ID（第 {d.candidate_revision} 版）</div><div className="break-all font-mono">{d.candidate_id}</div></div>}
                          <div className="overflow-x-auto">
                            <table className="w-full">
                              <thead><tr><th className="th">#</th><th className="th">時間</th><th className="th">HTTP</th><th className="th">結果</th><th className="th">request_id</th></tr></thead>
                              <tbody>
                                {d.attempts.map((a) => (
                                  <tr key={a.id}>
                                    <td className="td num">{a.attempt_no}</td>
                                    <td className="td num text-xs">{dt(a.started_at)}</td>
                                    <td className="td num">{a.http_status ?? '—'}</td>
                                    <td className="td text-xs">{a.error ? issueText(a.error) : 'OK'}</td>
                                    <td className="td font-mono text-xs">{a.request_id}</td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </>
                      )}
                      <button className="self-start text-[13px] font-medium text-accent hover:text-accent-dark" onClick={() => setShowJson((v) => !v)}>{showJson ? '收起' : '看'}送出的 JSON</button>
                      {showJson && <pre className="max-h-80 overflow-auto rounded-[10px] bg-stone-75 p-3 font-mono text-xs leading-relaxed">{JSON.stringify(d?.payload || q.payload_preview, null, 2)}</pre>}
                    </div>
                  )}
                </div>
              )}
            </section>
          </aside>
        </div>
      )}
    </div>
  )
}

function StatusLine({ tone, title, sub }) {
  const icon =
    tone === 'ok' ? <Check size={18} /> : tone === 'bad' ? <Alert /> : <Clock />
  const ring = tone === 'bad' ? 'bg-red-50 text-red-700' : tone === 'idle' ? 'bg-stone-100 text-stone-500' : 'bg-accent-soft text-accent'
  return (
    <div className="flex items-center gap-3">
      <span className={`grid h-10 w-10 flex-none place-items-center rounded-full ${ring} ${tone === 'wait' ? 'animate-ring' : ''}`}>{icon}</span>
      <div className="min-w-0">
        <div className="text-sm font-medium">{title}</div>
        {sub && <div className="truncate text-[13px] text-stone-500">{sub}</div>}
      </div>
    </div>
  )
}
