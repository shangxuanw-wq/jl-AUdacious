import { useCallback, useEffect, useState } from 'react'
import { api } from '../api.js'
import { Plus, shortTime } from '../ui.jsx'

export const ROLE_INFO = {
  admin: { label: '管理員', desc: '全部功能，加上管理成員和信箱設定', chip: 'chip-hot' },
  member: { label: '成員', desc: '建立、送出報價，回信、收信', chip: 'chip-mute' },
  viewer: { label: '唯讀', desc: '只能看，可以下載附件', chip: 'chip-line' },
}
const ROLES = ['admin', 'member', 'viewer']
const VIA = { env: '固定管理員', email: '個別設定', domain: '整個網域' }

export default function Members({ me }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ target: '', role: 'member', note: '' })
  const [flash, setFlash] = useState(null)

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
    if (await run(() => api('/admin/access', { method: 'POST', body: { ...form, target } }), `已加入 ${target}`)) setForm({ target: '', role: form.role, note: '' })
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

  return (
    <div className="space-y-5">
      <div className="animate-rise">
        <h1 className="text-[26px] font-black">成員與權限</h1>
        <p className="mt-1 text-sm text-stone-500">只有名單裡的帳號能登入。可以一個一個 email 加，也可以開放整個公司網域。</p>
      </div>

      {error && <p className="error">{error}</p>}
      {flash && <p key={flash.text} className="notice animate-drop">{flash.text}</p>}

      <form onSubmit={add} className="card animate-rise space-y-4 p-5" style={{ animationDelay: '.06s' }}>
        <h2 className="text-base font-bold">加入</h2>
        <div className="grid gap-3.5 md:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <div>
            <label className="label" htmlFor="m-target">Email 或 @網域</label>
            <input
              id="m-target"
              className="input"
              placeholder="someone@gmail.com　或　@jauhlirn.com"
              value={form.target}
              onChange={(e) => setForm({ ...form, target: e.target.value })}
              required
              autoComplete="off"
            />
            <p className="mt-1.5 text-xs text-stone-500">
              {isDomain ? '整個網域的人都能用自己的 Google 帳號登入（gmail.com 這類公用信箱不能整個開放）。' : '只有這個帳號能登入，任何 Google 帳號都可以（含 Gmail）。'}
            </p>
          </div>
          <div>
            <label className="label" htmlFor="m-note">備註（可空白）</label>
            <input id="m-note" className="input" maxLength={200} placeholder="例如 業務 Amy" value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} />
          </div>
        </div>
        <fieldset>
          <legend className="label">角色</legend>
          <div className="grid gap-2.5 sm:grid-cols-3">
            {ROLES.map((r) => (
              <label
                key={r}
                className={`flex cursor-pointer items-start gap-3 rounded-xl border p-3.5 transition ${form.role === r ? 'border-accent bg-accent-soft/50 ring-[3px] ring-accent/10' : 'border-stone-200 hover:border-accent-line'}`}
              >
                <input type="radio" name="role" className="mt-1 accent-[#C2410C]" checked={form.role === r} onChange={() => setForm({ ...form, role: r })} />
                <span>
                  <span className="block text-sm font-medium">{ROLE_INFO[r].label}</span>
                  <span className="block text-xs text-stone-500">{ROLE_INFO[r].desc}</span>
                </span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="flex justify-end">
          <button className="btn-primary" disabled={busy || !form.target.trim()}><Plus />加入名單</button>
        </div>
      </form>

      <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.12s' }}>
        <div className="flex items-baseline justify-between px-5 pb-2 pt-5">
          <h2 className="text-base font-bold">名單 <span className="font-normal text-stone-500">{data.fixed_admins.length + data.rules.length}</span></h2>
        </div>
        {data.fixed_admins.map((email) => (
          <Row key={email} icon="person" title={email} sub={loginOf[email] ? `最後登入 ${shortTime(loginOf[email].last_login_at)}` : '還沒登入過'}>
            <span className="chip-hot">管理員</span>
            <span className="chip-line" title="寫在系統設定（ALLOWED_EMAILS），這裡不能改">固定</span>
          </Row>
        ))}
        {data.rules.map((r) => {
          const l = r.kind === 'email' ? loginOf[r.value] : null
          const domainUsers = r.kind === 'domain' ? data.logins.filter((x) => x.via === 'domain' && x.email.endsWith(`@${r.value}`)).length : 0
          const sub = [
            r.note,
            r.kind === 'domain' ? `整個網域・已登入過 ${domainUsers} 人` : l ? `最後登入 ${shortTime(l.last_login_at)}` : '還沒登入過',
          ]
            .filter(Boolean)
            .join('・')
          return (
            <Row key={r.id} icon={r.kind === 'domain' ? 'domain' : 'person'} title={r.kind === 'domain' ? `@${r.value}` : r.value} sub={sub} off={!r.active} hl={flash?.id === r.id}>
              <select
                className="input min-h-[36px] w-auto py-0 text-[13px]"
                aria-label={`${r.value} 的角色`}
                value={r.role}
                disabled={busy}
                onChange={(e) => patch(r, { role: e.target.value })}
              >
                {ROLES.map((x) => <option key={x} value={x}>{ROLE_INFO[x].label}</option>)}
              </select>
              <Switch on={r.active} disabled={busy} label={r.active ? '啟用中' : '已停用'} onChange={(v) => patch(r, { active: v })} />
              <button className="btn-ghost btn-sm text-stone-500 hover:text-red-700" disabled={busy} onClick={() => remove(r)}>移除</button>
            </Row>
          )
        })}
        {data.rules.length === 0 && <p className="border-t border-stone-100 px-5 py-6 text-sm text-stone-500">除了固定管理員，還沒加任何人。</p>}
      </section>

      <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.18s' }}>
        <h2 className="px-5 pb-2 pt-5 text-base font-bold">最近登入</h2>
        {data.logins.length === 0 && <p className="px-5 pb-5 text-sm text-stone-500">還沒有人登入過。</p>}
        {data.logins.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px]">
              <thead className="bg-stone-75">
                <tr><th className="th pl-5">帳號</th><th className="th">角色</th><th className="th">依據</th><th className="th">最後登入</th><th className="th">次數</th><th className="th pr-5" /></tr>
              </thead>
              <tbody>
                {data.logins.map((l) => (
                  <tr key={l.email} className="transition-colors hover:bg-[#FFFBF7]">
                    <td className="td pl-5">{l.name ? <><div>{l.name}</div><div className="text-xs text-stone-500">{l.email}</div></> : l.email}</td>
                    <td className="td"><span className={ROLE_INFO[l.role]?.chip || 'chip-mute'}>{ROLE_INFO[l.role]?.label || l.role}</span></td>
                    <td className="td text-[13px] text-stone-600">{VIA[l.via] || l.via}</td>
                    <td className="td num text-[13px] text-stone-600">{shortTime(l.last_login_at)}</td>
                    <td className="td num text-[13px] text-stone-600">{l.login_count}</td>
                    <td className="td pr-5 text-right">
                      {l.via === 'domain' && (
                        <button className="text-[13px] font-medium text-accent hover:text-accent-dark" onClick={() => { setForm({ target: l.email, role: l.role, note: l.name }); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>
                          個別設定
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="px-5 pb-5 pt-3 text-xs text-stone-500">角色或名單變更後，最慢 30 秒生效；已登入的人不用重新登入。目前登入：{me?.email}</p>
      </section>
    </div>
  )
}

function Row({ icon, title, sub, off, hl, children }) {
  return (
    <div className={`flex flex-wrap items-center gap-x-4 gap-y-2.5 border-t border-stone-100 px-5 py-3.5 transition-colors ${hl ? 'animate-fade bg-accent-soft/40' : ''} ${off ? 'opacity-60' : ''}`}>
      <span className={`grid h-10 w-10 flex-none place-items-center rounded-full ${icon === 'domain' ? 'bg-stone-100 text-stone-600' : 'bg-accent-soft text-accent'}`} aria-hidden="true">
        {icon === 'domain' ? (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 10h.01M15 10h.01" /></svg>
        ) : (
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></svg>
        )}
      </span>
      <div className="min-w-0 flex-[1_1_240px]">
        <div className={`truncate font-medium ${icon === 'domain' ? 'font-mono' : ''}`}>{title}</div>
        <div className="truncate text-xs text-stone-500">{sub}</div>
      </div>
      <div className="flex flex-wrap items-center gap-2.5">{children}</div>
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
