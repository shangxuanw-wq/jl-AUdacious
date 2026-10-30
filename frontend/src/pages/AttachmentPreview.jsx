import { lazy, Suspense, useEffect } from 'react'
import { createPortal } from 'react-dom'
import { Arrow, Cube, FileIcon, ImageIcon } from '../ui.jsx'

const Viewer3D = lazy(() => import('./Viewer3D.jsx'))

const KINDS = {
  image: ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'],
  pdf: ['pdf'],
  stl: ['stl'],
  step: ['stp', 'step'],
  iges: ['igs', 'iges'],
}

export const ext = (name) => (name.includes('.') ? name.split('.').pop().toLowerCase() : '')
export const previewKind = (name) => Object.keys(KINDS).find((k) => KINDS[k].includes(ext(name))) || null

const TAG = { step: 'STEP', iges: 'IGES', stl: 'STL', image: '圖片', pdf: 'PDF' }
const Download = () => (
  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>
)

const tagOf = (name) => TAG[previewKind(name)] || (ext(name) || '檔案').toUpperCase()
const thumbSrc = (rfqId, n) => `/api/rfqs/${rfqId}/attachments/${n}?inline=1`

const sizeText = (n) => (!n ? '' : n >= 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`)

export default function AttachmentPreview({ rfqId, attachments, index, onIndex, onClose }) {
  const a = attachments[index]
  const kind = previewKind(a.filename)
  const url = `/api/rfqs/${rfqId}/attachments/${a.n}`

  useEffect(() => {
    const onKey = (e) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft' && index > 0) onIndex(index - 1)
      if (e.key === 'ArrowRight' && index < attachments.length - 1) onIndex(index + 1)
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [index, attachments.length, onClose, onIndex])

  const go = (i) => i >= 0 && i < attachments.length && onIndex(i)
  const arrow = 'absolute top-1/2 z-10 grid h-11 w-11 -translate-y-1/2 place-items-center rounded-full bg-white/95 text-stone-700 shadow-lift ring-1 ring-stone-200 transition hover:text-accent'

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-stone-900/60 p-2 sm:p-6" onClick={onClose}>
      <div className="card flex w-full max-w-[1600px] flex-col overflow-hidden" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={a.filename}>
        <div className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <div className="truncate text-[15px] font-semibold" title={a.filename}>{a.filename}</div>
            <div className="num mt-0.5 text-xs text-stone-500">
              {[tagOf(a.filename), sizeText(a.size), attachments.length > 1 ? `${index + 1} / ${attachments.length}` : ''].filter(Boolean).join('・')}
            </div>
          </div>
          <a className="btn-ghost btn-sm gap-1.5" href={url}><Download /><span className="hidden sm:inline">下載</span></a>
          <button type="button" className="grid h-9 w-9 flex-none place-items-center rounded-[10px] text-stone-500 transition hover:bg-stone-100 hover:text-stone-900" onClick={onClose} aria-label="關閉" title="關閉（Esc）">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
          </button>
        </div>

        <div className="relative mx-3 min-h-0 flex-1 sm:mx-5">
          {index > 0 && (
            <button type="button" className={`${arrow} left-3`} onClick={() => go(index - 1)} aria-label="上一個附件" title="上一個（←）">
              <span className="rotate-180"><Arrow size={20} /></span>
            </button>
          )}
          {index < attachments.length - 1 && (
            <button type="button" className={`${arrow} right-3`} onClick={() => go(index + 1)} aria-label="下一個附件" title="下一個（→）">
              <Arrow size={20} />
            </button>
          )}
          {kind === 'image' && (
            <div className="flex h-full items-center justify-center overflow-auto rounded-lg bg-stone-100">
              <img key={url} src={`${url}?inline=1`} alt={a.filename} className="max-h-full max-w-full object-contain" />
            </div>
          )}
          {kind === 'pdf' && <iframe key={url} title={a.filename} src={`${url}?inline=1`} className="h-full w-full rounded-lg border border-stone-200" />}
          {(kind === 'stl' || kind === 'step' || kind === 'iges') && (
            <Suspense fallback={<p className="p-6 text-center text-sm text-stone-500">載入 3D 檢視器…</p>}>
              <Viewer3D key={url} url={url} kind={kind} />
            </Suspense>
          )}
          {!kind && (
            <div className="flex h-full flex-col items-center justify-center gap-3 rounded-lg bg-stone-100 p-6 text-center text-sm text-stone-600">
              <p>這種格式（.{ext(a.filename) || '無副檔名'}）沒辦法在站內預覽，請下載後用對應的軟體開啟。</p>
              <a className="btn-primary" href={url}>下載 {a.filename}</a>
            </div>
          )}
        </div>

        {attachments.length > 1 ? (
          <div className="flex gap-2 overflow-x-auto px-3 py-3 sm:px-5" role="tablist" aria-label="附件">
            {attachments.map((x, i) => {
              const k = previewKind(x.filename)
              const on = i === index
              return (
                <button
                  key={x.n}
                  type="button"
                  role="tab"
                  aria-selected={on}
                  onClick={() => go(i)}
                  title={x.filename}
                  className={`flex w-[132px] flex-none items-center gap-2.5 rounded-xl border p-2 text-left transition ${on ? 'border-accent bg-accent-soft/40 ring-[3px] ring-accent/10' : 'border-stone-200 hover:border-accent-line'}`}
                >
                  <span className={`grid h-10 w-10 flex-none place-items-center overflow-hidden rounded-lg ${k === 'step' ? 'bg-accent-soft text-accent' : 'bg-stone-100 text-stone-600'}`} aria-hidden="true">
                    {k === 'image' ? (
                      <img src={thumbSrc(rfqId, x.n)} alt="" className="h-full w-full object-cover" />
                    ) : k === 'stl' || k === 'step' || k === 'iges' ? (
                      <Cube size={22} />
                    ) : (
                      <FileIcon size={20} />
                    )}
                  </span>
                  <span className="min-w-0">
                    <span className={`block text-[13px] ${on ? 'font-semibold text-stone-900' : 'font-medium text-stone-700'}`}>{tagOf(x.filename)}</span>
                    <span className="num block text-[11px] text-stone-500">{sizeText(x.size)}</span>
                  </span>
                </button>
              )
            })}
          </div>
        ) : (
          <div className="h-3 sm:h-5" />
        )}
      </div>
    </div>,
    document.body,
  )
}
