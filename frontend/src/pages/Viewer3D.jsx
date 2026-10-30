import { useEffect, useRef, useState } from 'react'
import occtJsUrl from 'occt-import-js/dist/occt-import-js.js?url'
import occtWasmUrl from 'occt-import-js/dist/occt-import-js.wasm?url'

const MAX_EDGE_TRIANGLES = 400000 // 超過就不畫邊線，避免太慢

async function fetchBuffer(url, signal) {
  const res = await fetch(url, { credentials: 'same-origin', signal })
  if (!res.ok) {
    let msg = `下載失敗（${res.status}）`
    try {
      msg = (await res.json()).detail || msg
    } catch {
      /* 不是 JSON */
    }
    throw new Error(msg)
  }
  return res.arrayBuffer()
}

function parseCad(buffer, format) {
  return new Promise((resolve, reject) => {
    const worker = new Worker(new URL('../lib/occtWorker.js', import.meta.url))
    const abs = (u) => new URL(u, window.location.href).href
    worker.onmessage = (ev) => {
      worker.terminate()
      ev.data.ok ? resolve(ev.data.meshes) : reject(new Error(ev.data.error))
    }
    worker.onerror = (e) => {
      worker.terminate()
      reject(new Error(e.message || '解析元件載入失敗'))
    }
    worker.postMessage({ jsUrl: abs(occtJsUrl), wasmUrl: abs(occtWasmUrl), format, buffer }, [buffer])
  })
}

const fmt = (v) => (v >= 100 ? v.toFixed(1) : v.toFixed(2)).replace(/\.?0+$/, '')

/** kind：'stl' | 'step' | 'iges' */
export default function Viewer3D({ url, kind }) {
  const box = useRef(null)
  const api = useRef(null)
  const [stage, setStage] = useState('download')
  const [error, setError] = useState('')
  const [info, setInfo] = useState(null)
  const [edges, setEdges] = useState(true)

  useEffect(() => {
    const ctrl = new AbortController()
    let disposed = false
    let cleanup = () => {}

    ;(async () => {
      try {
        const buffer = await fetchBuffer(url, ctrl.signal)
        if (disposed) return
        setStage('parse')
        const [THREE, { OrbitControls }, { STLLoader }] = await Promise.all([
          import('three'),
          import('three/addons/controls/OrbitControls.js'),
          import('three/addons/loaders/STLLoader.js'),
        ])

        const geos = []
        if (kind === 'stl') {
          const g = new STLLoader().parse(buffer)
          g.computeVertexNormals() // 很多 STL 檔裡的法向量是 0，一律重算
          geos.push({ geo: g, color: null })
        } else {
          const meshes = await parseCad(buffer, kind)
          for (const m of meshes) {
            const g = new THREE.BufferGeometry()
            g.setAttribute('position', new THREE.BufferAttribute(m.position, 3))
            if (m.normal) g.setAttribute('normal', new THREE.BufferAttribute(m.normal, 3))
            g.setIndex(new THREE.BufferAttribute(m.index, 1))
            if (!m.normal) g.computeVertexNormals()
            geos.push({ geo: g, color: m.color })
          }
        }
        if (disposed) {
          geos.forEach((x) => x.geo.dispose())
          return
        }
        if (geos.length === 0) throw new Error('檔案裡沒有可以顯示的實體')

        const el = box.current
        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0xf2eee8)
        const group = new THREE.Group()
        const edgeGroup = new THREE.Group()
        let triangles = 0
        for (const { geo } of geos) triangles += (geo.index ? geo.index.count : geo.getAttribute('position').count) / 3
        for (const { geo, color } of geos) {
          const mat = new THREE.MeshStandardMaterial({
            color: color ? new THREE.Color(color[0], color[1], color[2]) : 0xc4bbad,
            metalness: 0.15,
            roughness: 0.55,
            side: THREE.DoubleSide,
            polygonOffset: true,
            polygonOffsetFactor: 1,
            polygonOffsetUnits: 1,
          })
          group.add(new THREE.Mesh(geo, mat))
          if (triangles <= MAX_EDGE_TRIANGLES) {
            edgeGroup.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25), new THREE.LineBasicMaterial({ color: 0x44403c })))
          }
        }
        scene.add(group, edgeGroup)

        const bbox = new THREE.Box3().setFromObject(group)
        const size = bbox.getSize(new THREE.Vector3())
        const center = bbox.getCenter(new THREE.Vector3())
        const radius = Math.max(size.length() / 2, 1e-3)

        const renderer = new THREE.WebGLRenderer({ antialias: true })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        el.appendChild(renderer.domElement)

        const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100)
        camera.up.set(0, 0, 1) // CAD 檔多半 Z 軸朝上
        scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8a8a, 1.6))
        const sun = new THREE.DirectionalLight(0xffffff, 1.6)
        sun.position.set(0.5, 0.3, 1)
        camera.add(sun)
        scene.add(camera)

        const controls = new OrbitControls(camera, renderer.domElement)
        controls.target.copy(center)
        const render = () => renderer.render(scene, camera)
        controls.addEventListener('change', render)

        const VIEWS = { iso: [1, -1, 0.8], front: [0, -1, 0], top: [0, 0, 1], right: [1, 0, 0] }
        const setView = (name) => {
          const d = new THREE.Vector3(...VIEWS[name]).normalize()
          const dist = radius / Math.sin((camera.fov * Math.PI) / 360) * 1.05
          camera.up.set(0, 0, 1)
          if (name === 'top') camera.up.set(0, 1, 0)
          camera.position.copy(center).addScaledVector(d, dist)
          controls.target.copy(center)
          camera.lookAt(center)
          controls.update()
          render()
        }

        const resize = () => {
          const w = el.clientWidth || 1
          const h = el.clientHeight || 1
          renderer.setSize(w, h)
          camera.aspect = w / h
          camera.updateProjectionMatrix()
          render()
        }
        const ro = new ResizeObserver(resize)
        ro.observe(el)
        resize()
        setView('iso')

        api.current = {
          setView,
          setEdges: (on) => {
            edgeGroup.visible = on
            render()
          },
        }
        setInfo({
          size: [size.x, size.y, size.z],
          triangles: Math.round(triangles),
          parts: geos.length,
          edges: triangles <= MAX_EDGE_TRIANGLES,
        })
        setStage('ready')

        cleanup = () => {
          ro.disconnect()
          controls.dispose()
          scene.traverse((o) => {
            o.geometry?.dispose()
            o.material?.dispose()
          })
          renderer.dispose()
          renderer.domElement.remove()
        }
      } catch (e) {
        if (!disposed && e.name !== 'AbortError') {
          setError(e.message || String(e))
          setStage('error')
        }
      }
    })()

    return () => {
      disposed = true
      ctrl.abort()
      api.current = null
      cleanup()
    }
  }, [url, kind])

  const toggleEdges = () => {
    api.current?.setEdges(!edges)
    setEdges(!edges)
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg bg-stone-100" ref={box}>
        {stage !== 'ready' && (
          <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-sm text-stone-500">
            {stage === 'download' && '下載檔案中…'}
            {stage === 'parse' && (kind === 'stl' ? '處理模型中…' : '解析 STEP 中…（第一次會先載入約 7 MB 的解析元件，之後就快了）')}
            {stage === 'error' && <span className="text-red-700">{error}</span>}
          </div>
        )}
      </div>
      {stage === 'ready' && info && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-sm">
          <span>
            <span className="text-stone-500">外形尺寸 </span>
            <span className="num font-medium">
              {info.size.map(fmt).join(' × ')} {kind === 'stl' ? '（STL 沒有單位，通常是 mm）' : 'mm'}
            </span>
          </span>
          <span className="text-xs text-stone-500">
            {info.parts > 1 ? `${info.parts} 個實體・` : ''}
            {info.triangles.toLocaleString()} 面
          </span>
          <div className="ml-auto flex flex-wrap gap-1.5">
            {[
              ['iso', '等角'],
              ['front', '正面'],
              ['top', '上面'],
              ['right', '右側'],
            ].map(([k, label]) => (
              <button key={k} className="btn-ghost px-2.5 py-1 text-xs" onClick={() => api.current?.setView(k)}>
                {label}
              </button>
            ))}
            {info.edges && (
              <button className="btn-ghost px-2.5 py-1 text-xs" onClick={toggleEdges}>
                {edges ? '隱藏邊線' : '顯示邊線'}
              </button>
            )}
          </div>
        </div>
      )}
      {stage === 'ready' && <p className="mt-1 text-xs text-stone-400">左鍵拖曳旋轉・滾輪縮放・右鍵拖曳平移（手機：單指旋轉、雙指縮放）</p>}
    </div>
  )
}
