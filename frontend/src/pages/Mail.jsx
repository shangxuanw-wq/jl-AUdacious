import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, dt } from '../api.js'
import { Badge } from '../labels.jsx'
import { Arrow } from '../ui.jsx'

const MSG_STATUS = {
  created: ['已建單', 'chip-hot'],
  updated: ['已更新', 'chip-hot'],
  ignored: ['略過', 'chip-mute'],
  error: ['讀不懂', 'chip-bad'],
}

const REASONS = {
  own_message: '我方寄出的信',
  sender_not_allowed: '寄件人不在允許清單',
  rfq_closed: '詢價單已結案',
  older_than_latest: '比目前採用的信舊',
  missing_rfq_number: '找不到「詢價編號：」',
  bad_rfq_number: '詢價編號格式不對',
  missing_item: '找不到「工件1｜」',
  bad_item_line: '工件那一行格式不對',
  bad_quantity: '數量不對',
  subject_rfq_mismatch: '主旨與內文的詢價編號不同',
  multiple_items_ignored: '有多個工件，只讀了工件1',
  same_spec_resent: '同一版規格重寄，不用重新報價',
  spec_revision_up: '規格改版，請照新版重新報價',
  older_spec_revision: '比目前的規格版次舊',
  spec_revision_missing: '信上沒有「規格版次」',
  bad_spec_revision: '規格版次格式不對',
}

const CONNECT_ERRORS = {
  oauth: '授權流程中斷，請再試一次。',
  token: 'Google 授權失敗，請再試一次。',
  no_refresh_token: 'Google 沒有給長期授權，請再按一次「連接信箱」。',
  wrong_mailbox: '登入的不是指定的信箱',
}

const TABS = [
  ['all', '全部'],
  ['created', '建單'],
  ['updated', '更新'],
  ['ignored', '略過'],
  ['error', '讀不懂'],
]

const p2 = (n) => String(n).padStart(2, '0')
/** 剛剛／5 分鐘前／今天 21:42／昨天 21:42／10/28 21:42 */
export const relTime = (v, now = Date.now()) => {
  if (!v) return '—'
  const d = new Date(v)
  const diff = (now - d.getTime()) / 60000
  if (diff < 1) return '剛剛'
  if (diff < 60) return `${Math.floor(diff)} 分鐘前`
  const hm = `${p2(d.getHours())}:${p2(d.getMinutes())}`
  const day = (x) => new Date(x).toDateString()
  if (day(d) === day(now)) return `今天 ${hm}`
  if (day(d) === day(now - 86400000)) return `昨天 ${hm}`
  return `${d.getMonth() + 1}/${d.getDate()} ${hm}`
}

/** 「[詢價][測試] AUD-RFQ-2026-0004 工件… ×5」→ 標籤＋其餘文字 */
const splitSubject = (subject = '', rfqNo = '') => {
  const tags = []
  let rest = subject.trim()
  for (let m; (m = rest.match(/^\[([^\]]{1,12})\]\s*/)); ) {
    if (m[1] !== '詢價') tags.push(m[1])
    rest = rest.slice(m[0].length)
  }
  if (rfqNo && rest.startsWith(rfqNo)) rest = rest.slice(rfqNo.length).trim()
  return { tags, rest }
}

const reason = (e) => (e ? e.split(',').map((x) => REASONS[x] || x).join('、') : '')

export default function Mail({ me }) {
  const isAdmin = me?.role === 'admin'
  const canEdit = me?.role !== 'viewer'
  const [params, setParams] = useSearchParams()
  const [s, setS] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [last, setLast] = useState(null)

  const load = useCallback(() => api('/gmail/status').then(setS).catch((e) => setError(e.message)), [])
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
  const box = s.mailboxes[0]
  const connErr = params.get('error')
  const tab = TABS.some(([k]) => k === params.get('tab')) ? params.get('tab') : 'all'
  const setTab = (k) => {
    const next = new URLSearchParams(params)
    if (k === 'all') next.delete('tab')
    else next.set('tab', k)
    setParams(next, { replace: true })
  }
  const count = (k) => s.messages.filter((m) => k === 'all' || m.status === k).length
  const shown = s.messages.filter((m) => tab === 'all' || m.status === tab)

  // 健康狀態：有錯誤＝紅；超過 5 分鐘沒成功收信＝黃；其他＝綠
  const okAgo = box?.last_poll_ok_at ? (Date.now() - new Date(box.last_poll_ok_at).getTime()) / 60000 : Infinity
  const health = !box ? null : box.last_error ? 'bad' : okAgo > 5 ? 'warn' : 'ok'
  const HEALTH = {
    ok: ['bg-emerald-500', '收信正常', 'text-stone-900'],
    warn: ['bg-amber-500', '有一陣子沒收到信箱回應', 'text-amber-800'],
    bad: ['bg-red-600', '收信失敗', 'text-red-700'],
  }

  return (
    <div className="space-y-5">
      <div className="animate-rise">
        <h1 className="text-[26px] font-black">信箱</h1>
        <p className="mt-1 text-sm text-stone-500">收到詢價信會自動建立詢價單。</p>
      </div>
      {params.get('connected') && <p className="notice">信箱已連接。</p>}
      {connErr && (
        <p className="error">
          {CONNECT_ERRORS[connErr] || '連接失敗'}{connErr === 'wrong_mailbox' && params.get('got') ? `（你登入的是 ${params.get('got')}，請改用 ${s.expected_mailbox}）` : ''}
        </p>
      )}
      {!s.configured && <p className="notice">信箱功能還沒設定完成（缺 Google 設定或 MAIL_TOKEN_KEY）。</p>}
      {error && <p className="error">{error}</p>}

      <section className="card relative z-10 animate-rise px-5 py-4" style={{ animationDelay: '.06s' }}>
        {box ? (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
            <span className="relative grid h-10 w-10 flex-none place-items-center rounded-full bg-stone-100" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-stone-600"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="m3 7 9 6 9-6" /></svg>
              <i className={`absolute -right-0.5 -top-0.5 h-3 w-3 rounded-full ring-2 ring-white ${HEALTH[health][0]} ${health === 'ok' ? 'animate-ring' : ''}`} />
            </span>
            <div className="min-w-0 flex-[1_1_220px]">
              <div className={`text-[15px] font-semibold ${HEALTH[health][2]}`}>{HEALTH[health][1]}</div>
              <div className="text-xs leading-relaxed text-stone-500">
                <span className="font-mono">{box.email}</span>・每分鐘自動檢查・{health !== 'ok' ? `上次成功 ${relTime(box.last_poll_ok_at)}` : `最後檢查 ${relTime(box.last_poll_at)}`}
                {s.sender_allow.length > 0 && <>・只收 {s.sender_allow.join('、')}</>}
              </div>
              {box.last_error && (
                <div className="mt-1 text-xs text-red-700">
                  {box.last_error.startsWith('auth:') ? 'Google 授權失效，請重新連接。' : box.last_error}
                  {isAdmin && box.last_error.startsWith('auth:') && <a className="ml-2 font-medium underline" href="/api/gmail/connect">重新連接</a>}
                </div>
              )}
              {last && <div className="mt-1 text-xs text-stone-500">剛剛收到 {last.new} 封新信。</div>}
            </div>
            <div className="ml-auto flex items-center gap-1.5">
              {canEdit && (
                <button className="btn-ghost btn-sm" disabled={busy} onClick={() => act(async () => setLast(await api('/gmail/poll', { method: 'POST' })))}>
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={busy ? 'animate-spin' : ''}><path d="M21 12a9 9 0 1 1-3-6.7L21 8M21 3v5h-5" /></svg>
                  {busy ? '收信中…' : '立即收信'}
                </button>
              )}
              {isAdmin && (
                <MoreMenu
                  items={[
                    {
                      label: '中斷連接',
                      danger: true,
                      onClick: () => window.confirm('中斷後系統就不會再讀這個信箱，確定？') && act(() => api('/gmail/disconnect', { method: 'POST' })),
                    },
                  ]}
                  info={`由 ${box.connected_by || '—'} 於 ${dt(box.connected_at)} 連接`}
                />
              )}
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-stone-600">還沒連接信箱。</span>
            {isAdmin ? (
              <a className={`btn-primary ${!s.configured ? 'pointer-events-none opacity-50' : ''}`} href="/api/gmail/connect">連接 {s.expected_mailbox}</a>
            ) : (
              <span className="text-sm text-stone-500">請管理員連接信箱。</span>
            )}
            <span className="text-xs text-stone-500">會跳到 Google，請用這個信箱登入並允許。</span>
          </div>
        )}
      </section>

      <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.12s' }}>
        <div className="flex flex-wrap items-center gap-3 border-b border-stone-100 px-4 py-3 sm:px-5">
          <h2 className="text-[15px] font-bold">收信紀錄</h2>
          <div className="flex w-full gap-1 rounded-xl bg-stone-100 p-1 sm:ml-auto sm:inline-flex sm:w-auto" role="tablist">
            {TABS.map(([k, label]) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={tab === k}
                onClick={() => setTab(k)}
                className={`min-h-[34px] flex-1 whitespace-nowrap rounded-[9px] px-1.5 text-[13px] font-medium transition sm:flex-none sm:px-3 ${tab === k ? 'bg-white text-accent-dark shadow-sm' : 'text-stone-500 hover:text-stone-900'}`}
              >
                {label}
                <span className={`num ml-1 ${k === 'error' && count(k) > 0 ? 'text-red-600' : 'text-stone-400'}`}>{count(k)}</span>
              </button>
            ))}
          </div>
        </div>
        {shown.length === 0 && <p className="px-5 py-10 text-center text-sm text-stone-500">{s.messages.length === 0 ? '還沒有收到詢價信' : '沒有這類的信'}</p>}
        {shown.map((m) => (
          <MessageRow key={m.id} m={m} />
        ))}
      </section>
    </div>
  )
}

function MessageRow({ m }) {
  const { tags, rest } = splitSubject(m.subject, m.rfq_number)
  const bad = m.status === 'error'
  const body = (
    <>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge map={MSG_STATUS} value={m.status} />
          {tags.map((t) => <span key={t} className="chip-line">{t}</span>)}
        </div>
        <div className="mt-1.5 flex min-w-0 flex-wrap items-baseline gap-x-2">
          {m.rfq_number && <span className="font-mono text-[15px] font-semibold">{m.rfq_number}</span>}
          <span className="min-w-0 truncate text-sm text-stone-700">{rest || (m.rfq_number ? '' : m.subject)}</span>
        </div>
        <div className="mt-0.5 truncate text-xs text-stone-500">{m.from_addr}・附件 {m.attachment_count}</div>
        {m.error && <div className={`mt-1 text-xs ${bad ? 'text-red-700' : 'text-stone-500'}`}>{reason(m.error)}</div>}
      </div>
      <div className="flex flex-none flex-col items-end gap-2 self-stretch">
        <span className="num whitespace-nowrap text-xs text-stone-500" title={dt(m.received_at)}>{relTime(m.received_at)}</span>
        {m.rfq_id && <span className="mt-auto text-stone-400 transition duration-200 group-hover:translate-x-1 group-hover:text-accent"><Arrow /></span>}
      </div>
    </>
  )
  const cls = `group flex gap-4 border-t border-stone-100 px-4 py-3.5 transition-colors first:border-t-0 sm:px-5 ${bad ? 'border-l-[3px] border-l-red-500 bg-red-50/40' : ''}`
  return m.rfq_id ? (
    <Link to={`/rfqs/${m.rfq_id}`} className={`${cls} hover:bg-[#FFFBF7]`}>{body}</Link>
  ) : (
    <div className={cls}>{body}</div>
  )
}

function MoreMenu({ items, info }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (!open) return
    const close = (e) => ref.current && !ref.current.contains(e.target) && setOpen(false)
    const esc = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', esc)
    }
  }, [open])
  return (
    <div className="relative" ref={ref}>
      <button type="button" className="grid h-9 w-9 place-items-center rounded-[10px] text-stone-500 transition hover:bg-stone-100 hover:text-stone-900" onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} aria-label="更多">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="19" cy="12" r="1.8" /></svg>
      </button>
      {open && (
        <div className="card absolute right-0 top-full z-20 mt-1.5 w-60 animate-drop overflow-hidden p-1 shadow-lift" role="menu">
          {info && <div className="px-3 py-2 text-xs text-stone-500">{info}</div>}
          {items.map((it) => (
            <button
              key={it.label}
              type="button"
              role="menuitem"
              className={`block w-full rounded-lg px-3 py-2 text-left text-sm transition ${it.danger ? 'text-red-700 hover:bg-red-50' : 'hover:bg-stone-100'}`}
              onClick={() => {
                setOpen(false)
                it.onClick()
              }}
            >
              {it.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
