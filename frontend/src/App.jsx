import { useEffect, useState } from 'react'
import { Link, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api.js'
import Login from './pages/Login.jsx'
import RfqList from './pages/RfqList.jsx'
import RfqDetail from './pages/RfqDetail.jsx'
import QuoteDetail from './pages/QuoteDetail.jsx'
import MockPanel from './pages/MockPanel.jsx'
import Mail from './pages/Mail.jsx'

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
    `rounded-md px-3 py-1.5 text-sm ${isActive ? 'bg-stone-900 text-white' : 'text-stone-600 hover:bg-stone-200'}`

  return (
    <div className="min-h-screen">
      <header className="border-b border-stone-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <Link to="/" className="mr-2 flex items-center gap-2 font-bold">
            <span className="grid h-7 w-7 place-items-center rounded-md bg-accent text-xs text-white">JL</span>
            估價
          </Link>
          <nav className="flex gap-1">
            <NavLink to="/" end className={tab}>詢價單</NavLink>
            <NavLink to="/mail" className={tab}>信箱</NavLink>
            {cfg?.mock_enabled && <NavLink to="/mock" className={tab}>假澳得仕</NavLink>}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-xs text-stone-500">
            {cfg && !cfg.target_is_partner_prod && (
              <span className="rounded-full bg-accent-soft px-2 py-0.5 font-medium text-accent-dark">送往：假澳得仕（開發）</span>
            )}
            {cfg?.target_is_partner_prod && (
              <span className="rounded-full bg-red-50 px-2 py-0.5 font-medium text-red-700">送往：澳得仕正式站</span>
            )}
            <span className="hidden sm:inline">{me.email}</span>
            <button className="btn-ghost px-2.5 py-1 text-xs" onClick={logout}>登出</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Routes>
          <Route path="/" element={<RfqList />} />
          <Route path="/rfqs/:id" element={<RfqDetail cfg={cfg} />} />
          <Route path="/quotes/:id" element={<QuoteDetail cfg={cfg} />} />
          {cfg?.mock_enabled && <Route path="/mock" element={<MockPanel />} />}
          <Route path="/mail" element={<Mail />} />
          <Route path="/login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<div className="text-sm text-stone-500">找不到這個頁面</div>} />
        </Routes>
      </main>
    </div>
  )
}
