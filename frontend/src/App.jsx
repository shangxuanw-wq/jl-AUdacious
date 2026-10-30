import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api.js'
import Login from './pages/Login.jsx'
import RfqList from './pages/RfqList.jsx'
import RfqDetail from './pages/RfqDetail.jsx'
import QuoteDetail from './pages/QuoteDetail.jsx'
import MockPanel from './pages/MockPanel.jsx'
import Mail from './pages/Mail.jsx'
import Members, { ROLE_INFO } from './pages/Members.jsx'

export default function App() {
  const [me, setMe] = useState(undefined)
  const [cfg, setCfg] = useState(null)
  const loc = useLocation()

  useEffect(() => {
    api('/auth/me')
      .then(setMe)
      .catch(() => setMe({ email: null }))
  }, [])

  useEffect(() => {
    if (me?.email) api('/config').then(setCfg).catch(() => setCfg(null))
  }, [me?.email])

  if (me === undefined) return <div className="p-8 text-sm text-stone-500">載入中…</div>
  if (!me.email) {
    if (loc.pathname !== '/login') return <Navigate to="/login" replace />
    return <Login me={me} />
  }

  const logout = async () => {
    await api('/auth/logout', { method: 'POST' })
    window.location.href = '/login'
  }

  const tab = ({ isActive }) =>
    `rounded-lg px-3.5 py-2 text-sm transition-colors ${isActive ? 'bg-accent-soft font-medium text-accent-dark' : 'text-stone-500 hover:bg-stone-100 hover:text-stone-900'}`

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-[1680px] flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2.5 sm:gap-x-4 sm:px-6 xl:px-10">
          <Link to="/" className="flex items-center gap-2.5 font-bold text-stone-900 sm:mr-3">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[13px] font-black text-white">JL</span>
            <span className="hidden text-[15px] sm:inline">估價中心</span>
          </Link>
          <nav className="flex gap-1">
            <NavLink to="/" end className={tab}>詢價單</NavLink>
            <NavLink to="/mail" className={tab}>信箱</NavLink>
            {me.role === 'admin' && <NavLink to="/members" className={tab}>成員</NavLink>}
            {cfg?.mock_enabled && <NavLink to="/mock" className={tab}>模擬對方</NavLink>}
          </nav>
          <div className="ml-auto flex items-center gap-2 sm:gap-3">
            {cfg && !cfg.target_is_partner_prod && <span className="chip-hot">測試環境</span>}
            {me.role === 'viewer' && <span className="chip-line">唯讀</span>}
            <span className="grid h-[34px] w-[34px] place-items-center rounded-full bg-accent text-[13px] font-bold uppercase text-white" title={`${me.name ? me.name + '・' : ''}${me.email}（${ROLE_INFO[me.role]?.label || ''}）`} aria-label={me.email}>
              {(me.email || '?').replace(/^key:/, '').slice(0, 1)}
            </span>
            <button className="btn-ghost btn-sm" onClick={logout}>登出</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1680px] px-4 pb-12 pt-6 sm:px-6 xl:px-10">
        <Routes>
          <Route path="/" element={<RfqList cfg={cfg} me={me} />} />
          <Route path="/rfqs/:id" element={<RfqDetail cfg={cfg} me={me} />} />
          <Route path="/quotes/:id" element={<QuoteDetail cfg={cfg} me={me} />} />
          {cfg?.mock_enabled && <Route path="/mock" element={<MockPanel />} />}
          <Route path="/mail" element={<Mail me={me} />} />
          {me.role === 'admin' && <Route path="/members" element={<Members me={me} />} />}
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<div className="text-sm text-stone-500">找不到這個頁面</div>} />
        </Routes>
      </main>
    </div>
  )
}
