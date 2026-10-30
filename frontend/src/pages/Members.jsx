import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Plus, shortTime } from '../ui.jsx'

export const ROLE_INFO = {
  admin: { label: '管理員', desc: '全部功能，加上管理成員和信箱設定', chip: 'chip-hot' },
  member: { label: '成員', desc: '建立、送出報價，回信、收信', chip: 'chip-mute' },
  viewer: { label: '唯讀', desc: '只能看，可以下載附件', chip: 'chip-line' },
}
const ROLES = ['admin', 'member', 'viewer']

export default function Members({ me }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ target: '', role: 'member', note: '' })
  const [flash, setFlash] = useState(null)
  const [adding, setAdding] = useState(false)

  const load = useCallback(() => api('/admin/access').then(setData).catch((e) => setError(e.message)), [])
  useEffect(() => {
    load()
  }, [load])

  const run = async (fn, okMsg) => {
    setBusy(true)
    setError('')
    try {
      const r = await fn()
      await load()
      if (okMsg) setFlash({ text: okMsg, id: r?.id })
      return true
    } catch (e) {
      setError(e.message)
      return false
    } finally {
      setBusy(false)
    }
  }

  const add = async (e) => {
    e.preventDefault()
    const target = form.target.trim()
    if (await run(() => api('/admin/access', { method: 'POST', body: { ...form, target } }), `已加入 ${target}`)) {
      setForm({ target: '', role: form.role, note: '' })
      setAdding(false)
    }
  }
  const patch = (r, body) => run(() => api(`/admin/access/${r.id}`, { method: 'PATCH', body }))
  const remove = (r) => {
    const name = r.kind === 'domain' ? `@${r.value}（整個網域）` : r.value
    if (!window.confirm(`把 ${name} 從名單移除？移除後就不能登入了。`)) return
    run(() => api(`/admin/access/${r.id}`, { method: 'DELETE' }), `已移除 ${name}`)
  }

  if (!data) return error ? <p className="error">{error}</p> : <p className="text-sm text-stone-500">載入中…</p>
  const loginOf = Object.fromEntries(data.logins.map((l) => [l.email, l]))
  const isDomain = form.target.trim().startsWith('@') || (form.target.trim() && !form.target.includes('@'))
  const ruled = new Set([...data.fixed_admins, ...data.rules.filter((r) => r.kind === 'email').map((r) => r.value)])
  const domainUsers = data.logins.filter((l) => l.via === 'domain' && !ruled.has(l.email))
  const total = data.fixed_admins.length + data.rules.length + domainUsers.length
  const seen = (l) => (l ? `最後登入 ${shortTime(l.last_login_at)}・${l.login_count} 次` : '還沒登入過')
  const openFor = (target, role, note) => {
    setForm({ target, role, note })
    setAdding(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="space-y-5">
      <div className="flex animate-rise flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-black">成員與權限 <span className="text-lg font-medium text-stone-400">{total}</span></h1>
          <p className="mt-1 text-sm text-stone-500">只有名單裡的帳號能登入。</p>
        </div>
        {!adding && (
          <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
            <Plus />加入
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {flash && <p key={flash.text} className="notice animate-drop">{flash.text}</p>}

      {adding && (
        <form onSubmit={add} className="card animate-drop border-accent-line p-4 ring-4 ring-accent/5 sm:p-5">
          <div className="flex flex-wrap items-end gap-2.5">
            <div className="min-w-0 flex-[2_1_260px]">
              <label className="label" htmlFor="m-target">Email 或 @網域</label>
              <input
                id="m-target"
                className="input"
                placeholder="someone@gmail.com　或　@jauhlirn.com"
                value={form.target}
                onChange={(e) => setForm({ ...form, target: e.target.value })}
                required
                autoFocus
                autoComplete="off"
              />
            </div>
            <div className="min-w-0 flex-[1_1_160px]">
              <label className="label" htmlFor="m-note">備註</label>
              <input id="m-note" className="input" maxLength={200} placeholder="可空白" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
            </div>
            <div className="flex-[0_1_130px]">
              <label className="label" htmlFor="m-role">角色</label>
              <select id="m-role" className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_INFO[r].label}</option>)}
              </select>
            </div>
            <div className="flex flex-none gap-2">
              <button type="button" className="btn-ghost" onClick={() => setAdding(false)}>取消</button>
              <button className="btn-primary" disabled={busy || !form.target.trim()}>加入</button>
            </div>
          </div>
          <p className="mt-2 text-xs text-stone-500">
            {ROLE_INFO[form.role].label}：{ROLE_INFO[form.role].desc}。{form.target.trim() ? (isDomain ? '整個網域都能登入（公用信箱不能整個開放）。' : '只有這個帳號能登入。') : ''}
          </p>
        </form>
      )}

      <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.08s' }}>
        {data.fixed_admins.map((email) => (
          <Row key={email} name={loginOf[email]?.name} title={email} sub={seen(loginOf[email])}>
            <span className="chip-hot" title="寫在系統設定（ALLOWED_EMAILS），這裡不能改">管理員・固定</span>
          </Row>
        ))}
        {data.rules.map((r) => {
          const l = r.kind === 'email' ? loginOf[r.value] : null
          const n = r.kind === 'domain' ? data.logins.filter((x) => x.via === 'domain' && x.email.endsWith(`@${r.value}`)).length : 0
          return (
            <Row
              key={r.id}
              domain={r.kind === 'domain'}
              name={r.kind === 'domain' ? '' : l?.name || r.note}
              title={r.kind === 'domain' ? `@${r.value}` : r.value}
              note={r.kind === 'domain' ? r.note : l?.name && r.note && r.note !== l.name ? r.note : ''}
              sub={r.kind === 'domain' ? `整個網域・已登入過 ${n} 人` : seen(l)}
              off={!r.active}
              hl={flash?.id === r.id}
            >
              <select
                className="input min-h-[36px] w-[92px] py-0 text-[13px]"
                aria-label={`${r.value} 的角色`}
                value={r.role}
                disabled={busy}
                onChange={(e) => patch(r, { role: e.target.value })}
              >
                {ROLES.map((x) => <option key={x} value={x}>{ROLE_INFO[x].label}</option>)}
              </select>
              <Switch on={r.active} disabled={busy} label={r.active ? '啟用' : '停用'} onChange={(v) => patch(r, { active: v })} />
              <button type="button" className="grid h-9 w-9 place-items-center rounded-[10px] text-stone-400 transition hover:bg-red-50 hover:text-red-700 disabled:opacity-50" disabled={busy} onClick={() => remove(r)} aria-label={`移除 ${r.value}`} title="移除">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>
              </button>
            </Row>
          )
        })}
        {domainUsers.map((l) => (
          <Row key={l.email} name={l.name} title={l.email} sub={`透過網域登入・${seen(l)}`}>
            <span className={ROLE_INFO[l.role]?.chip || 'chip-mute'}>{ROLE_INFO[l.role]?.label || l.role}</span>
            <button type="button" className="btn-ghost btn-sm" onClick={() => openFor(l.email, l.role, l.name)}>個別設定</button>
          </Row>
        ))}
        {total === data.fixed_admins.length && <p className="border-t border-stone-100 px-5 py-6 text-sm text-stone-500">除了固定管理員，還沒加任何人。</p>}
      </section>

      <p className="text-xs text-stone-500">變更最慢 30 秒生效，不用重新登入。</p>
    </div>
  )
}

function Row({ name, title, sub, note, domain, off, hl, children }) {
  const initial = (name || title).replace(/^@/, '').slice(0, 1).toUpperCase()
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-2.5 border-t border-stone-100 px-4 py-3.5 transition-colors first:border-t-0 hover:bg-[#FFFBF7] sm:px-5 ${hl ? 'animate-fade bg-accent-soft/40' : ''} ${off ? 'opacity-55' : ''}`}>
      <span className={`grid h-10 w-10 flex-none place-items-center rounded-full text-sm font-bold ${domain ? 'bg-stone-100 text-stone-600' : 'bg-accent-soft text-accent'}`} aria-hidden="true">
        {domain ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 10h.01M15 10h.01" /></svg>
        ) : (
          initial
        )}
      </span>
      <div className="min-w-0 flex-[1_1_220px]">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className={`truncate font-medium ${domain ? 'font-mono' : ''}`}>{name || title}</span>
          {note && <span className="chip-line flex-none">{note}</span>}
        </div>
        {name && <div className="truncate text-[13px] text-stone-600">{title}</div>}
        <div className="truncate text-xs text-stone-500">{sub}</div>
      </div>
      <div className="ml-auto flex flex-wrap items-center gap-2">{children}</div>
    </div>
  )
}

function Switch({ on, onChange, label, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className="flex min-h-[36px] items-center gap-2 text-[13px] text-stone-600 disabled:opacity-50"
    >
      <span className={`relative block h-6 w-10 flex-none rounded-full transition-colors duration-200 ${on ? 'bg-accent' : 'bg-stone-300'}`}>
        <span className={`absolute left-0 top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 ${on ? 'translate-x-[18px]' : 'translate-x-0.5'}`} />
      </span>
      {label}
    </button>
  )
}
