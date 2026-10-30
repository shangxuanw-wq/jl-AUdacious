// 共用的小元件：進度、圖示

// 進度（跟後端 list_rfqs 的 stage 同一套）
export const STAGE = {
  todo: { label: '待報價', done: 1, chip: 'chip-hot' },
  draft: { label: '草稿', done: 1, chip: 'chip-mute' },
  failed: { label: '送出失敗', done: 1, chip: 'chip-bad' },
  sending: { label: '送出中', done: 1, chip: 'chip-hot' },
  review: { label: '審核中', done: 2, chip: 'chip-hot' },
  published: { label: '已發布', done: 4, chip: 'chip-mute' },
  closed: { label: '完成', done: 4, chip: 'chip-mute' },
}

const DISPATCH_STAGE = { pending: 'sending', sending: 'sending', retry_wait: 'sending', accepted: 'review', duplicate: 'review', published: 'published' }

export function stageOf(rfqStatus, quoteStatus, dispatchStatus) {
  if (rfqStatus === 'closed') return 'closed'
  if (!quoteStatus) return 'todo'
  if (quoteStatus === 'draft') return 'draft'
  if (DISPATCH_STAGE[dispatchStatus]) return DISPATCH_STAGE[dispatchStatus]
  return quoteStatus === 'failed' || dispatchStatus ? 'failed' : 'review'
}

export const shortTime = (v) => {
  if (!v) return ''
  const d = new Date(v)
  const p = (n) => String(n).padStart(2, '0')
  return `${p(d.getMonth() + 1)}/${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

/** 四步進度條。steps: [{label, sub}]，done: 已完成幾步（下一步會閃動）。 */
export function Stepper({ steps, done, className = '', style }) {
  return (
    <section className={`card flex flex-wrap items-center gap-x-2 gap-y-3 px-5 py-4 animate-rise ${className}`} style={style} aria-label="進度">
      {steps.map((s, i) => {
        const state = i < done ? 'done' : i === done ? 'now' : 'todo'
        const last = i === steps.length - 1
        return (
          <div key={s.label} className={`flex min-w-0 items-center gap-2.5 ${last ? 'flex-[1_1_140px] sm:flex-none' : 'flex-[1_1_140px] sm:flex-[1_1_160px]'}`}>
            <span
              className={`grid h-7 w-7 flex-none place-items-center rounded-full text-xs font-bold ${
                state === 'done' ? 'bg-accent text-white' : state === 'now' ? 'animate-ring border-2 border-accent bg-white text-accent' : 'bg-stone-100 text-stone-500'
              }`}
            >
              {state === 'done' ? <Check size={14} /> : i + 1}
            </span>
            <div className="min-w-0">
              <div className={`text-sm font-medium ${state === 'now' ? 'text-accent' : state === 'todo' ? 'text-stone-500' : ''}`}>{s.label}</div>
              <div className="text-xs text-stone-500">{s.sub || '—'}</div>
            </div>
            {!last && (
              <span className="hidden h-[3px] min-w-[24px] flex-1 overflow-hidden rounded bg-stone-200 sm:block">
                {i < done && <i className="block h-full origin-left animate-grow bg-accent" />}
              </span>
            )}
          </div>
        )
      })}
    </section>
  )
}

const svg = (size, children, sw = 2) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {children}
  </svg>
)

export const Check = ({ size = 16 }) => svg(size, <path d="m5 12 5 5 9-10" />, 2.6)
export const Plus = ({ size = 16 }) => svg(size, <path d="M12 5v14M5 12h14" />, 2.2)
export const Chevron = ({ size = 16, className = '' }) => <span className={className}>{svg(size, <path d="m6 9 6 6 6-6" />)}</span>
export const Arrow = ({ size = 18 }) => svg(size, <path d="m9 6 6 6-6 6" />)
export const Search = ({ size = 16 }) => svg(size, <><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></>)
export const Doc = ({ size = 16 }) => svg(size, <><path d="M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></>)
export const Clock = ({ size = 18 }) => svg(size, <><circle cx="12" cy="12" r="8" /><path d="M12 8v4l3 2" /></>, 2.2)
export const Alert = ({ size = 18 }) => svg(size, <><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 2.4 18a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>)
export const Cube = ({ size = 48, className = '' }) => (
  <svg className={className} width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
    <path d="M32 6 56 19v26L32 58 8 45V19z" />
    <path d="M8 19l24 13 24-13M32 32v26" />
  </svg>
)
export const ImageIcon = ({ size = 48, className = '' }) => (
  <svg className={className} width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
    <rect x="8" y="12" width="48" height="40" rx="4" />
    <path d="M8 42l14-12 12 10 8-6 14 10" />
    <circle cx="44" cy="24" r="4" />
  </svg>
)
export const FileIcon = ({ size = 48, className = '' }) => (
  <svg className={className} width={size} height={size} viewBox="0 0 64 64" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
    <path d="M38 8H18a3 3 0 0 0-3 3v42a3 3 0 0 0 3 3h28a3 3 0 0 0 3-3V19z" />
    <path d="M38 8v11h11M24 34h16M24 42h16" />
  </svg>
)
