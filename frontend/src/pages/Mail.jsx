import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, dt } from '../api.js'
import { Badge } from '../labels.jsx'

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

const reason = (e) => (e ? e.split(',').map((x) => REASONS[x] || x).join('、') : '')

export default function Mail() {
  const [params] = useSearchParams()
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

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[26px] font-black">信箱</h1>
        <p className="mt-1 text-sm text-stone-500">連接 <span className="font-mono">{s.expected_mailbox}</span> 後，系統每分鐘讀一次主旨含 AUD-RFQ 的新信，自動建立或更新詢價單。只讀，不會改信箱內容。</p>
      </div>
      {params.get('connected') && <p className="notice">信箱已連接。</p>}
      {connErr && (
        <p className="error">
          {CONNECT_ERRORS[connErr] || '連接失敗'}{connErr === 'wrong_mailbox' && params.get('got') ? `（你登入的是 ${params.get('got')}，請改用 ${s.expected_mailbox}）` : ''}
        </p>
      )}
      {!s.configured && <p className="notice">信箱功能還沒設定完成（缺 Google 設定或 MAIL_TOKEN_KEY）。</p>}
      {error && <p className="error">{error}</p>}

      <section className="card animate-rise space-y-3 p-5">
        {box ? (
          <>
            <div className="flex flex-wrap items-center gap-3">
              <span className="chip-hot">已連接</span>
              <span className="font-mono text-sm">{box.email}</span>
              <span className="text-xs text-stone-500">由 {box.connected_by || '—'} 於 {dt(box.connected_at)} 連接</span>
              <div className="ml-auto flex gap-2">
                <button className="btn-primary" disabled={busy} onClick={() => act(async () => setLast(await api('/gmail/poll', { method: 'POST' })))}>{busy ? '收信中…' : '立即收信'}</button>
                <button className="btn-ghost" disabled={busy} onClick={() => window.confirm('中斷後系統就不會再讀這個信箱，確定？') && act(() => api('/gmail/disconnect', { method: 'POST' }))}>中斷連接</button>
              </div>
            </div>
            <p className="text-xs text-stone-500">
              上次收信：{dt(box.last_poll_at)}　上次成功：{dt(box.last_poll_ok_at)}
              {s.sender_allow.length > 0 && <>　只收：{s.sender_allow.join('、')}</>}
            </p>
            {box.last_error && (
              <p className="error">
                收信失敗：{box.last_error}{box.last_error.startsWith('auth:') && '（授權失效，請重新連接）'}
                {box.last_error.startsWith('auth:') && <a className="ml-2 underline" href="/api/gmail/connect">重新連接</a>}
              </p>
            )}
            {last && <p className="text-xs text-stone-500">剛剛收到 {last.new} 封新信。</p>}
          </>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-sm text-stone-600">還沒連接信箱。</span>
            <a className={`btn-primary ${!s.configured ? 'pointer-events-none opacity-50' : ''}`} href="/api/gmail/connect">連接 {s.expected_mailbox}</a>
            <span className="text-xs text-stone-500">會跳到 Google，請用這個信箱登入並允許。</span>
          </div>
        )}
      </section>

      <section className="space-y-2">
        <h2 className="text-base font-bold">最近收到的詢價信</h2>
        <div className="card animate-rise overflow-x-auto" style={{ animationDelay: '.08s' }}>
          <table className="w-full min-w-[720px]">
            <thead className="bg-stone-75">
              <tr>
                <th className="th">收到</th>
                <th className="th">主旨</th>
                <th className="th">寄件人</th>
                <th className="th">結果</th>
                <th className="th">詢價單</th>
                <th className="th">附件</th>
              </tr>
            </thead>
            <tbody>
              {s.messages.length === 0 && <tr><td className="td text-stone-500" colSpan={6}>還沒有</td></tr>}
              {s.messages.map((m) => (
                <tr key={m.id} className="transition-colors hover:bg-[#FFFBF7]">
                  <td className="td text-xs">{dt(m.received_at)}</td>
                  <td className="td text-sm">{m.subject}</td>
                  <td className="td text-xs">{m.from_addr}</td>
                  <td className="td text-xs">
                    <Badge map={MSG_STATUS} value={m.status} />
                    {m.error && <div className="mt-1 text-stone-500">{reason(m.error)}</div>}
                  </td>
                  <td className="td font-mono text-xs">{m.rfq_id ? <Link className="text-accent-dark hover:underline" to={`/rfqs/${m.rfq_id}`}>{m.rfq_number}</Link> : m.rfq_number || '—'}</td>
                  <td className="td num">{m.attachment_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
