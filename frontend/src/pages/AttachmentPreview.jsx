import { lazy, Suspense, useEffect } from 'react'
import { createPortal } from 'react-dom'

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
      <div className="card flex w-full max-w-6xl flex-col p-3 sm:p-4" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-label={a.filename}>
        <div className="mb-3 flex items-center gap-2">
          <button className="btn-ghost px-2 py-1" disabled={index === 0} onClick={() => onIndex(index - 1)} aria-label="上一個附件">‹</button>
          <button className="btn-ghost px-2 py-1" disabled={index === attachments.length - 1} onClick={() => onIndex(index + 1)} aria-label="下一個附件">›</button>
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{a.filename}</div>
            <div className="text-xs text-stone-500">
              {index + 1} / {attachments.length}
              {a.size ? `・${sizeText(a.size)}` : ''}
            </div>
          </div>
          <a className="btn-ghost px-3 py-1.5" href={url}>下載</a>
          <button className="btn-ghost px-3 py-1.5" onClick={onClose} aria-label="關閉">✕</button>
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
