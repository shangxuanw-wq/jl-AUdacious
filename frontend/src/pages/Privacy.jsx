export default function Privacy() {
  return (
    <div className="mx-auto max-w-2xl px-5 py-12">
      <div className="mb-6 flex items-center gap-2.5 font-bold">
        <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-[13px] font-black text-white">JL</span>
        JL 估價中心
      </div>
      <article className="card animate-rise space-y-4 p-7 text-[15px] leading-relaxed text-stone-700">
        <h1 className="text-2xl font-black text-stone-900">隱私權政策</h1>
        <p>JL 估價中心（rfq.jauhlirn.com）是兆臨內部使用的報價系統，只開放給管理員加入名單的帳號登入。</p>
        <h2 className="pt-2 text-base font-bold text-stone-900">我們使用的 Google 帳號資料</h2>
        <p>用 Google 登入時，我們只取得你的 email、名字與 Google 帳號編號，用來確認你是否在名單內、決定你的權限，並記錄最後登入時間。我們不會讀取你的 Gmail、雲端硬碟或其他 Google 資料。</p>
        <h2 className="pt-2 text-base font-bold text-stone-900">資料的保存與分享</h2>
        <p>上述資料存放在本系統的資料庫，只供系統管理使用，不會出售或提供給第三方。管理員把你從名單移除後，你就無法再登入；如需刪除登入紀錄，請聯絡管理員。</p>
        <h2 className="pt-2 text-base font-bold text-stone-900">聯絡我們</h2>
        <p>
          有任何問題請寄信至 <a className="text-accent hover:text-accent-dark" href="mailto:jl-jimmy@jauhlirn.com">jl-jimmy@jauhlirn.com</a>。
        </p>
        <p className="pt-2 text-xs text-stone-500">最後更新：2026-10-30</p>
      </article>
    </div>
  )
}
