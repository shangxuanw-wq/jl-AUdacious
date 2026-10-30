import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api.js'
import { Plus, Search, shortTime } from '../ui.jsx'

export const ROLE_INFO = {
  admin: { label: '管理員', desc: '全部功能，加上管理成員和信箱設定', chip: 'chip-hot' },
  member: { label: '成員', desc: '建立、送出報價，回信、收信', chip: 'chip-mute' },
  viewer: { label: '唯讀', desc: '只能看，可以下載附件', chip: 'chip-line' },
}
const ROLES = ['admin', 'member', 'viewer']

// 角色權限對照（跟後端 require_user／require_admin 一致）
const MATRIX = [
  ['查看詢價單、報價單、附件', ['admin', 'member', 'viewer']],
  ['建立、修改、送出報價', ['admin', 'member']],
  ['寄回信、立即收信', ['admin', 'member']],
  ['連接／中斷信箱', ['admin']],
  ['管理成員與權限', ['admin']],
]

const FILTERS = [
  ['all', '全部'],
  ['admin', '管理員'],
  ['member', '成員'],
  ['viewer', '唯讀'],
  ['off', '已停用'],
]

const COLS = 'md:grid md:grid-cols-[minmax(0,1fr)_112px_104px_96px_132px_44px] md:items-center md:gap-x-4'

export default function Members({ me }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [form, setForm] = useState({ target: '', role: 'member', note: '' })
  const [flash, setFlash] = useState(null)
  const [adding, setAdding] = useState(false)
  const [filter, setFilter] = useState('all')
  const [q, setQ] = useState('')

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

  // 固定管理員＋名單規則＋透過網域登入的人，整理成同一張表
  const items = useMemo(() => {
    if (!data) return []
    const loginOf = Object.fromEntries(data.logins.map((l) => [l.email, l]))
    const ruled = new Set([...data.fixed_admins, ...data.rules.filter((r) => r.kind === 'email').map((r) => r.value)])
    return [
      ...data.fixed_admins.map((email) => ({ key: email, type: 'fixed', email, name: loginOf[email]?.name, role: 'admin', active: true, login: loginOf[email] })),
      ...data.rules.map((r) => ({
        key: `r${r.id}`,
        type: r.kind,
        rule: r,
        email: r.kind === 'domain' ? `@${r.value}` : r.value,
        name: r.kind === 'domain' ? '' : loginOf[r.value]?.name || '',
        note: r.note,
        role: r.role,
        active: r.active,
        login: r.kind === 'email' ? loginOf[r.value] : null,
        domainCount: r.kind === 'domain' ? data.logins.filter((x) => x.via === 'domain' && x.email.endsWith(`@${r.value}`)).length : 0,
      })),
      ...data.logins
        .filter((l) => l.via === 'domain' && !ruled.has(l.email))
        .map((l) => ({ key: l.email, type: 'via-domain', email: l.email, name: l.name, role: l.role, active: true, login: l })),
    ]
  }, [data])

  if (!data) return error ? <p className="error">{error}</p> : <p className="text-sm text-stone-500">載入中…</p>
  const isDomain = form.target.trim().startsWith('@') || (form.target.trim() && !form.target.includes('@'))
  const count = (f) => items.filter((x) => (f === 'all' ? true : f === 'off' ? !x.active : x.active && x.role === f)).length
  const needle = q.trim().toLowerCase()
  const shown = items.filter(
    (x) => (filter === 'all' || (filter === 'off' ? !x.active : x.active && x.role === filter)) && (!needle || `${x.email} ${x.name || ''} ${x.note || ''}`.toLowerCase().includes(needle)),
  )
  const lastLogin = data.logins.reduce((m, l) => (!m || l.last_login_at > m ? l.last_login_at : m), null)
  const openFor = (target, role, note) => {
    setForm({ target, role, note })
    setAdding(true)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="space-y-5">
      <div className="flex animate-rise flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[26px] font-black">成員與權限</h1>
          <p className="mt-1 text-sm text-stone-500">
            只有名單裡的帳號能登入・共 {items.length} 個帳號{lastLogin ? `・最近一次登入 ${shortTime(lastLogin)}` : ''}
          </p>
        </div>
        {!adding && (
          <button type="button" className="btn-primary" onClick={() => setAdding(true)}>
            <Plus />加入成員
          </button>
        )}
      </div>

      {error && <p className="error">{error}</p>}
      {flash && <p key={flash.text} className="notice animate-drop">{flash.text}</p>}

      {adding && (
        <form onSubmit={add} className="card animate-drop border-accent-line p-4 ring-4 ring-accent/5 sm:p-5">
          <h2 className="mb-3 text-[15px] font-bold">加入成員</h2>
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

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="card animate-rise overflow-hidden" style={{ animationDelay: '.12s' }}>
          <div className="flex flex-wrap items-center gap-3 border-b border-stone-100 px-4 py-3 sm:px-5">
            <div className="-mx-1 max-w-full overflow-x-auto px-1"><div className="inline-flex gap-1 whitespace-nowrap rounded-xl bg-stone-100 p-1" role="tablist">
              {FILTERS.map(([k, label]) => (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={filter === k}
                  onClick={() => setFilter(k)}
                  className={`min-h-[32px] rounded-[9px] px-3 text-[13px] font-medium transition ${filter === k ? 'bg-white text-accent-dark shadow-sm' : 'text-stone-500 hover:text-stone-900'}`}
                >
                  {label} <span className="num text-stone-400">{count(k)}</span>
                </button>
              ))}
            </div></div>
            <label className="relative ml-auto w-full max-w-[280px] flex-[1_1_200px]">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-stone-500"><Search /></span>
              <input type="search" className="input min-h-[38px] pl-9 text-[13px]" placeholder="搜尋 email、名字、備註" aria-label="搜尋成員" value={q} onChange={(e) => setQ(e.target.value)} />
            </label>
          </div>

          <div className={`hidden bg-stone-75 px-5 py-2 text-xs font-medium text-stone-500 ${COLS}`}>
            <span>帳號</span>
            <span>角色</span>
            <span>權限來源</span>
            <span>狀態</span>
            <span>最後登入</span>
            <span />
          </div>

          {shown.map((x) => (
            <MemberRow key={x.key} x={x} busy={busy} hl={x.rule && flash?.id === x.rule.id} onPatch={patch} onRemove={remove} onPromote={() => openFor(x.email, x.role, x.name)} />
          ))}
          {shown.length === 0 && <p className="border-t border-stone-100 px-5 py-10 text-center text-sm text-stone-500">沒有符合的帳號</p>}
        </section>

        <aside className="card animate-rise overflow-hidden" style={{ animationDelay: '.18s' }}>
          <h2 className="px-5 pb-2 pt-4 text-[15px] font-bold">角色權限</h2>
          <table className="w-full text-[13px]">
            <thead>
              <tr className="bg-stone-75 text-xs text-stone-500">
                <th className="py-2 pl-5 text-left font-medium">功能</th>
                {ROLES.map((r) => <th key={r} className="w-14 py-2 text-center font-medium last:pr-3">{ROLE_INFO[r].label}</th>)}
              </tr>
            </thead>
            <tbody>
              {MATRIX.map(([label, allow]) => (
                <tr key={label} className="border-t border-stone-100">
                  <td className="py-2.5 pl-5 pr-2 text-stone-700">{label}</td>
                  {ROLES.map((r) => (
                    <td key={r} className="text-center last:pr-3">
                      {allow.includes(r) ? <span className="font-bold text-accent" aria-label="可以">✓</span> : <span className="text-stone-300" aria-label="不行">—</span>}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="border-t border-stone-100 px-5 py-3 text-xs leading-relaxed text-stone-500">
            個別 email 的設定優先於整個網域；停用個別 email 可以擋掉網域裡的某個人。變更最慢 30 秒生效，不用重新登入。
          </p>
        </aside>
      </div>
    </div>
  )
}

function MemberRow({ x, busy, hl, onPatch, onRemove, onPromote }) {
  const domain = x.type === 'domain'
  const initial = (x.name || x.email).replace(/^@/, '').slice(0, 1).toUpperCase()
  const source = { fixed: '固定管理員', email: '個別設定', domain: '整個網域', 'via-domain': `網域 @${x.email.split('@')[1]}` }[x.type]
  const r = x.rule
  return (
    <div className={`flex flex-wrap items-center gap-x-3 gap-y-2.5 border-t border-stone-100 px-4 py-3 transition-colors first:border-t-0 hover:bg-[#FFFBF7] sm:px-5 ${COLS} ${hl ? 'animate-fade bg-accent-soft/40' : ''}`}>
      <div className={`flex min-w-0 flex-[1_1_100%] items-center gap-3 md:flex-none ${x.active ? '' : 'opacity-55'}`}>
        <span className={`grid h-9 w-9 flex-none place-items-center rounded-full text-[13px] font-bold ${domain ? 'bg-stone-100 text-stone-600' : 'bg-accent-soft text-accent'}`} aria-hidden="true">
          {domain ? (
            <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6M9 10h.01M15 10h.01" /></svg>
          ) : (
            initial
          )}
        </span>
        <div className="min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span className={`truncate text-sm font-medium ${domain ? 'font-mono' : ''}`}>{x.name || x.email}</span>
            {x.note && x.note !== x.name && <span className="chip-line flex-none">{x.note}</span>}
          </div>
          {x.name ? <div className="truncate text-xs text-stone-500">{x.email}</div> : domain ? <div className="text-xs text-stone-500">已登入過 {x.domainCount} 人</div> : null}
        </div>
      </div>

      <div>
        {r ? (
          <select className="input min-h-[34px] w-[104px] py-0 text-[13px]" aria-label={`${r.value} 的角色`} value={r.role} disabled={busy} onChange={(e) => onPatch(r, { role: e.target.value })}>
            {ROLES.map((k) => <option key={k} value={k}>{ROLE_INFO[k].label}</option>)}
          </select>
        ) : (
          <span className={ROLE_INFO[x.role]?.chip || 'chip-mute'}>{ROLE_INFO[x.role]?.label || x.role}</span>
        )}
      </div>

      <div className="text-xs text-stone-600">{source}</div>

      <div>
        {r ? (
          <Switch on={r.active} disabled={busy} label={r.active ? '啟用' : '停用'} onChange={(v) => onPatch(r, { active: v })} />
        ) : (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-stone-600"><i className="block h-2 w-2 rounded-full bg-emerald-500" />啟用</span>
        )}
      </div>

      <div className="num text-xs text-stone-500 max-md:basis-full max-md:order-last">
        {x.login ? (
          <>
            <span className="text-stone-700">{shortTime(x.login.last_login_at)}</span>
            <span className="ml-1.5 md:ml-0 md:block">共 {x.login.login_count} 次</span>
          </>
        ) : domain ? (
          '—'
        ) : (
          '還沒登入過'
        )}
      </div>

      <div className="ml-auto md:ml-0 md:text-right">
        {r ? (
          <button type="button" className="grid h-8 w-8 place-items-center rounded-lg text-stone-400 transition hover:bg-red-50 hover:text-red-700 disabled:opacity-50" disabled={busy} onClick={() => onRemove(r)} aria-label={`移除 ${r.value}`} title="移除">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></svg>
          </button>
        ) : x.type === 'via-domain' ? (
          <button type="button" className="text-xs font-medium text-accent hover:text-accent-dark" onClick={onPromote} title="幫這個人單獨設定角色">設定</button>
        ) : (
          <span className="grid h-8 w-8 place-items-center text-stone-300" title="寫在系統設定（ALLOWED_EMAILS），這裡不能改">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 0 1 8 0v3" /></svg>
          </span>
        )}
      </div>
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
      className="flex min-h-[34px] items-center gap-2 text-[13px] text-stone-600 disabled:opacity-50"
    >
      <span className={`relative block h-[22px] w-9 flex-none rounded-full transition-colors duration-200 ${on ? 'bg-accent' : 'bg-stone-300'}`}>
        <span className={`absolute left-0 top-0.5 h-[18px] w-[18px] rounded-full bg-white shadow transition-transform duration-200 ${on ? 'translate-x-[16px]' : 'translate-x-0.5'}`} />
      </span>
      {label}
    </button>
  )
}
