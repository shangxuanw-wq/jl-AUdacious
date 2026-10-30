import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, money } from '../api.js'
import { Badge, DISPATCH_STATUS, QUOTE_STATUS } from '../labels.jsx'
import { Chevron, Cube, FileIcon, ImageIcon, Plus, STAGE, Stepper, shortTime, stageOf } from '../ui.jsx'
import AttachmentPreview, { ext, previewKind } from './AttachmentPreview.jsx'
import QuoteForm from './QuoteForm.jsx'

const sizeText = (n) => (!n ? '' : n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

export default function RfqDetail({ cfg, me }) {
  const { id } = useParams()
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [creating, setCreating] = useState(false)
  const [preview, setPreview] = useState(null)
  const [rawOpen, setRawOpen] = useState(false)
  const nav = useNavigate()

  useEffect(() => {
    setData(null)
    api(`/rfqs/${id}`).then(setData).catch((e) => setError(e.message))
  }, [id])

  if (error) return <p className="error">{error}</p>
  if (!data) return <p className="text-sm text-stone-500">載入中…</p>
  const { rfq, quotes } = data
  const today = cfg?.today || new Date().toISOString().slice(0, 10)
  const latest = quotes[0]
  const stage = stageOf(rfq.status, latest?.status, latest?.latest_dispatch?.status)
  const st = STAGE[stage]
  const sentQuote = quotes.find((q) => q.latest_dispatch)
  const canQuote = rfq.status !== 'closed' && me?.role !== 'viewer'

  const create = async (body) => {
    const q = await api(`/rfqs/${id}/quotes`, { method: 'POST', body })
    nav(`/quotes/${q.id}`)
  }

  const steps = [
    { label: '收到詢價', sub: shortTime(rfq.created_at) },
    { label: '報價送出', sub: sentQuote ? shortTime(sentQuote.latest_dispatch.created_at) : '' },
    { label: '審核中', sub: stage === 'review' ? '等待對方確認' : '' },
    { label: '完成', sub: stage === 'published' ? '對方已發布' : '' },
  ]
  const fields = data.spec_fields || []

  return (
    <div className="space-y-5">
      <div className="flex animate-rise flex-wrap items-end gap-4">
        <div className="min-w-0 flex-[1_1_420px]">
          <Link to="/" className="text-[13px] text-stone-500 hover:text-stone-900">詢價單 ／</Link>
          <h1 className="mb-2.5 mt-1.5 font-mono text-[28px] font-semibold tracking-tight">{rfq.rfq_number}</h1>
          <div className="flex flex-wrap gap-2">
            <span className={st.chip}>{st.label}</span>
            <span className="chip-mute">規格版次 {rfq.spec_revision}</span>
            {rfq.is_test && <span className="chip-line">測試單</span>}
            <span className="chip-mute">需求日：{rfq.need_date || rfq.need_date_text || '請報交期'}</span>
          </div>
        </div>
        {canQuote && (
          <button className="btn-primary" onClick={() => setCreating((v) => !v)}>
            <Plus />
            {creating ? '收起報價' : '建立報價'}
          </button>
        )}
      </div>

      <Stepper steps={steps} done={st.done} style={{ animationDelay: '.06s' }} />

      {quotes.length > 0 && quotes.every((q) => (q.rfq_revision || 0) < rfq.spec_revision) && (
        <p className="notice">規格已改到第 {rfq.spec_revision} 版，現有報價都是舊版規格，請照新版重新報價。</p>
      )}

      {creating && (
        <div className="animate-drop">
          <QuoteForm rfq={rfq} today={today} submitLabel="建立草稿" onSubmit={create} onCancel={() => setCreating(false)} />
        </div>
      )}

      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_560px] flex-col gap-5">
          <section className="card animate-rise p-5" style={{ animationDelay: '.12s' }}>
            <div className="grid grid-cols-1 gap-4 border-b border-stone-100 pb-4 sm:grid-cols-3">
              <div><div className="label">品名</div><div className="text-[15px] font-medium">{rfq.item_name}</div></div>
              <div><div className="label">材質</div><div className="text-[15px] font-medium">{rfq.material_text}</div></div>
              <div>
                <div className="label">數量</div>
                <div className="num text-[22px] font-bold leading-tight">{rfq.quantity} <span className="text-[13px] font-normal text-stone-500">{rfq.unit}</span></div>
              </div>
            </div>
            {fields.length > 0 ? (
              <dl className="m-0 pt-1">
                {fields.map((f) => (
                  <div key={f.label} className="kv">
                    <dt>{f.label}</dt>
                    <dd className={f.label === '外形' ? 'num' : ''}>{f.value}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              !rfq.spec_text && <p className="pt-3 text-sm text-stone-500">詢價信沒有附規格說明。</p>
            )}
            {rfq.spec_text && (
              <>
                <button className="inline-flex min-h-[44px] items-center gap-1.5 text-sm font-medium text-accent hover:text-accent-dark" onClick={() => setRawOpen((v) => !v)} aria-expanded={rawOpen}>
                  {rawOpen ? '收合原信全文' : '看原信全文'}
                  <Chevron className={`transition-transform duration-200 ${rawOpen ? 'rotate-180' : ''}`} />
                </button>
                {(rawOpen || fields.length === 0) && (
                  <pre className="animate-drop whitespace-pre-wrap rounded-[10px] bg-stone-75 px-4 py-3.5 font-sans text-[13px] leading-relaxed text-stone-700">{rfq.spec_text}</pre>
                )}
              </>
            )}
          </section>

          <section className="card animate-rise p-5" style={{ animationDelay: '.18s' }}>
            <div className="mb-3.5 flex items-baseline justify-between">
              <h2 className="text-base font-bold">附件 <span className="font-normal text-stone-500">{data.attachments.length}</span></h2>
              {data.attachments.length > 0 && <span className="text-xs text-stone-500">點一下預覽</span>}
            </div>
            {data.attachments.length === 0 && <p className="text-sm text-stone-500">這封詢價信沒有附件。</p>}
            <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-3">
              {data.attachments.map((a, i) => (
                <Tile key={a.n} a={a} rfqId={rfq.id} onOpen={() => setPreview(i)} />
              ))}
            </div>
          </section>
        </div>

        <aside className="flex min-w-0 flex-[1_1_340px] flex-col gap-5 2xl:flex-[1_1_420px]">
          <section className="card animate-rise p-5" style={{ animationDelay: '.24s' }}>
            <h2 className="mb-3.5 text-base font-bold">報價</h2>
            {quotes.length === 0 && (
              <div className="rounded-xl border border-dashed border-stone-300 px-4 py-6 text-center text-sm text-stone-500">
                還沒有報價
                {canQuote && !creating && (
                  <div className="mt-3"><button className="btn-ghost btn-sm" onClick={() => setCreating(true)}><Plus size={14} />建立報價</button></div>
                )}
              </div>
            )}
            <div className="flex flex-col gap-3">
              {quotes.map((q, i) => (i === 0 ? <MainQuote key={q.id} q={q} /> : <SmallQuote key={q.id} q={q} />))}
            </div>
          </section>

          <section className="card animate-rise p-5" style={{ animationDelay: '.3s' }}>
            <h2 className="mb-3.5 text-base font-bold">聯絡人</h2>
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 flex-none place-items-center rounded-full bg-accent-soft font-bold uppercase text-accent">{(rfq.contact_name || rfq.contact_email || '?').slice(0, 1)}</span>
              <div className="min-w-0">
                <div className="font-medium">{rfq.contact_name || '—'}</div>
                <div className="truncate text-[13px] text-stone-500">{rfq.contact_email || ''}</div>
              </div>
            </div>
            <dl className="m-0 mt-3">
              {rfq.reply_to && rfq.reply_to !== rfq.contact_email && (
                <div className="kv"><dt>回覆給</dt><dd className="truncate">{rfq.reply_to}</dd></div>
              )}
              <div className="kv"><dt>來源</dt><dd>{rfq.source === 'email' ? `詢價信 ${rfq.mail_count} 封・自動建立` : '手動建立'}</dd></div>
            </dl>
          </section>
        </aside>
      </div>

      {preview !== null && data.attachments[preview] && (
        <AttachmentPreview rfqId={rfq.id} attachments={data.attachments} index={preview} onIndex={setPreview} onClose={() => setPreview(null)} />
      )}
    </div>
  )
}

function Tile({ a, rfqId, onOpen }) {
  const kind = previewKind(a.filename)
  const url = `/api/rfqs/${rfqId}/attachments/${a.n}`
  const is3d = kind === 'stl' || kind === 'step' || kind === 'iges'
  const tag = { step: 'STEP', iges: 'IGES', stl: 'STL', image: '圖片', pdf: 'PDF' }[kind] || (ext(a.filename) || '檔案').toUpperCase()
  const overlay = is3d ? '3D 預覽' : kind === 'image' ? '看大圖' : kind === 'pdf' ? '預覽' : '下載'
  const body = (
    <>
      <div className="grid h-24 place-items-center overflow-hidden rounded-lg bg-gradient-to-b from-stone-75 to-stone-100">
        {kind === 'image' ? (
          <img src={`${url}?inline=1`} alt="" loading="lazy" className="h-full w-full object-cover" />
        ) : is3d ? (
          <Cube size={52} className={kind === 'step' ? 'text-accent' : 'text-stone-600'} />
        ) : kind === 'pdf' ? (
          <FileIcon size={48} className="text-stone-600" />
        ) : (
          <ImageIcon size={48} className="text-stone-400" />
        )}
      </div>
      <div><span className={kind === 'step' ? 'chip-hot' : 'chip-mute'}>{tag}</span></div>
      <div className="truncate text-[13px] font-medium">{a.filename}</div>
      <div className="text-xs text-stone-500">{sizeText(a.size)}</div>
      <span className="absolute inset-0 flex items-center justify-center rounded-xl bg-accent/90 text-sm font-medium text-white opacity-0 transition-opacity duration-200 group-hover:opacity-100 group-focus-visible:opacity-100">
        {overlay}
      </span>
    </>
  )
  const cls = 'group relative flex flex-col gap-2.5 rounded-xl border border-stone-200 bg-white p-3.5 text-left transition duration-200 hover:-translate-y-[3px] hover:border-accent-line hover:shadow-lift'
  return kind ? (
    <button type="button" className={cls} onClick={onOpen} title={a.filename}>{body}</button>
  ) : (
    <a className={cls} href={url} title={a.filename}>{body}</a>
  )
}

function MainQuote({ q }) {
  const d = q.latest_dispatch
  const item = q.items[0]
  return (
    <Link to={`/quotes/${q.id}`} className="block rounded-xl border border-accent p-4 text-stone-900 ring-[3px] ring-accent/10 transition hover:shadow-lift">
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono font-semibold">{q.quote_no} <span className="font-normal text-stone-500">r{q.quote_revision}</span></span>
        {d ? <Badge map={DISPATCH_STATUS} value={d.status} /> : <Badge map={QUOTE_STATUS} value={q.status} />}
      </div>
      <div className="num mt-2.5 text-[26px] font-bold tracking-tight">
        {money(q.totals?.grand_total, q.currency)} <span className="text-xs font-normal text-stone-500">含稅</span>
      </div>
      {item && (
        <div className="mt-1.5 flex flex-wrap gap-x-3.5 gap-y-1 text-[13px] text-stone-500">
          <span className="num">{Number(item.unit_price).toLocaleString('zh-TW')} × {item.qty} {item.unit}</span>
          <span>{item.lead_days} 工作天</span>
        </div>
      )}
    </Link>
  )
}

function SmallQuote({ q }) {
  return (
    <Link to={`/quotes/${q.id}`} className="flex min-h-[48px] items-center justify-between gap-2 rounded-xl border border-stone-200 px-4 text-stone-900 transition hover:border-accent-line">
      <span className="font-mono text-sm">{q.quote_no} <span className="text-stone-500">r{q.quote_revision}</span></span>
      <span className="flex items-center gap-2">
        <span className="num text-[13px] text-stone-500">{money(q.totals?.grand_total, q.currency)}</span>
        <Badge map={QUOTE_STATUS} value={q.status} />
      </span>
    </Link>
  )
}
