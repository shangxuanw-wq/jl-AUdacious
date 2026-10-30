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

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-stretch justify-center bg-stone-900/60 p-2 sm:p-6" onClick={onClose}>
      <div className="card flex w-full max-w-[1600px] flex-col p-3 sm:p-4" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={a.filename}>
        <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2.5 border-b border-stone-100 pb-3">
          <div className="flex min-w-0 flex-[1_1_240px] items-center gap-3">
            <span className={`grid h-10 w-10 flex-none place-items-center rounded-lg ${kind === 'step' ? 'bg-accent-soft text-accent' : 'bg-stone-100 text-stone-600'}`} aria-hidden="true">
              {kind === 'stl' || kind === 'step' || kind === 'iges' ? <Cube size={22} /> : kind === 'pdf' ? <FileIcon size={20} /> : <ImageIcon size={20} />}
            </span>
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold" title={a.filename}>{a.filename}</div>
              <div className="mt-0.5 flex items-center gap-2 text-xs text-stone-500">
                <span className={kind === 'step' ? 'chip-hot' : 'chip-mute'}>{TAG[kind] || (ext(a.filename) || '檔案').toUpperCase()}</span>
                {a.size ? <span>{sizeText(a.size)}</span> : null}
              </div>
            </div>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {attachments.length > 1 && (
              <div className="flex items-center rounded-[10px] border border-stone-300 bg-white" role="group" aria-label="切換附件">
                <button type="button" className="grid h-9 w-9 place-items-center rounded-l-[10px] text-stone-700 transition hover:bg-stone-50 disabled:text-stone-300 disabled:hover:bg-white" disabled={index === 0} onClick={() => onIndex(index - 1)} aria-label="上一個附件" title="上一個（←）">
                  <span className="rotate-180"><Arrow size={16} /></span>
                </button>
                <span className="num min-w-[44px] border-x border-stone-200 px-2 text-center text-[13px] text-stone-600">{index + 1} / {attachments.length}</span>
                <button type="button" className="grid h-9 w-9 place-items-center rounded-r-[10px] text-stone-700 transition hover:bg-stone-50 disabled:text-stone-300 disabled:hover:bg-white" disabled={index === attachments.length - 1} onClick={() => onIndex(index + 1)} aria-label="下一個附件" title="下一個（→）">
                  <Arrow size={16} />
                </button>
              </div>
            )}
            <a className="btn-ghost btn-sm gap-1.5" href={url}><Download />下載</a>
            <button type="button" className="grid h-9 w-9 place-items-center rounded-[10px] text-stone-500 transition hover:bg-stone-100 hover:text-stone-900" onClick={onClose} aria-label="關閉" title="關閉（Esc）">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>
            </button>
          </div>
        </div>

        <div className="min-h-0 flex-1">
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
      </div>
    </div>,
    document.body,
  )
}
