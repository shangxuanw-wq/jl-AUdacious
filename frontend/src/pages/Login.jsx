import { useSearchParams } from 'react-router-dom'

const ERRORS = {
  not_allowed: '這個 Google 帳號不在白名單裡。',
  oauth: '登入流程中斷，請再試一次。',
  token: 'Google 登入失敗，請再試一次。',
  userinfo: '讀不到 Google 帳號資料，請再試一次。',
}

export default function Login({ me }) {
  const [params] = useSearchParams()
  const err = params.get('error')
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="card w-full max-w-sm p-8 text-center">
        <div className="mx-auto mb-4 grid h-12 w-12 place-items-center rounded-xl bg-accent text-lg font-bold text-white">JL</div>
        <h1 className="text-lg font-bold">JL × 澳得仕 估價</h1>
        <p className="mt-1 text-sm text-stone-500">只有白名單內的帳號可以登入</p>
        {err && <p className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{ERRORS[err] || '登入失敗'}</p>}
        {me?.login_configured === false ? (
          <p className="mt-6 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Google 登入還沒設定完成（缺 GOOGLE_CLIENT_ID／GOOGLE_CLIENT_SECRET／SESSION_SECRET／ALLOWED_EMAILS）。
          </p>
        ) : (
          <a href="/api/auth/login" className="btn-primary mt-6 w-full">用 Google 登入</a>
        )}
      </div>
    </div>
  )
}
