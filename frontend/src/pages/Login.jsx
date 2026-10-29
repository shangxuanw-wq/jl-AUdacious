import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { api } from '../api.js'

const ERRORS = {
  not_allowed: '這個 Google 帳號不在白名單裡。',
  oauth: '登入流程中斷，請再試一次。',
  token: 'Google 登入失敗，請再試一次。',
  userinfo: '讀不到 Google 帳號資料，請再試一次。',
}

export default function Login({ me }) {
  const [params] = useSearchParams()
  const err = params.get('error')
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [keyErr, setKeyErr] = useState('')

  const submitKey = async (e) => {
    e.preventDefault()
    setBusy(true)
    setKeyErr('')
    try {
      await api('/auth/key', { method: 'POST', body: { key, name } })
      window.location.replace('/')
    } catch (e2) {
      setKeyErr(e2.message)
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="card w-full max-w-sm p-8 text-center">
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-accent text-lg font-bold text-white">JL</div>
        <h1 className="text-lg font-bold">JL × 澳得仕 估價</h1>
        <p className="mt-1 text-sm text-stone-500">只有白名單內的帳號可以登入</p>
        {err && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{ERRORS[err] || '登入失敗'}</p>}
        {me?.google_login && <a href="/api/auth/login" className="btn-primary mt-6 w-full">用 Google 登入</a>}
        {me?.key_login && (
          <form onSubmit={submitKey} className="mt-6 space-y-3 text-left">
            {me?.google_login && <p className="text-center text-xs text-stone-400">或</p>}
            <div>
              <label className="label" htmlFor="key">臨時登入金鑰</label>
              <input id="key" type="password" autoComplete="current-password" className="input" value={key} onChange={(e) => setKey(e.target.value)} required />
            </div>
            <div>
              <label className="label" htmlFor="name">你的名字（記在操作紀錄）</label>
              <input id="name" className="input" value={name} maxLength={40} onChange={(e) => setName(e.target.value)} placeholder="例如 Jimmy" />
            </div>
            {keyErr && <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{keyErr}</p>}
            <button className={me?.google_login ? 'btn-ghost w-full' : 'btn-primary w-full'} disabled={busy || !key}>{busy ? '登入中…' : '登入'}</button>
          </form>
        )}
        {!me?.google_login && !me?.key_login && (
          <p className="mt-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">登入還沒設定完成（Google 登入或臨時金鑰都還沒設）。</p>
        )}
      </div>
    </div>
  )
}
