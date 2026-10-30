/* 在背景執行緒把 STEP / IGES 轉成三角網格（OpenCascade WASM），避免畫面卡住。 */
let occtPromise = null

self.onmessage = async (ev) => {
  const { jsUrl, wasmUrl, format, buffer } = ev.data
  try {
    if (!occtPromise) {
      importScripts(jsUrl)
      occtPromise = self.occtimportjs({ locateFile: () => wasmUrl })
    }
    const occt = await occtPromise
    const content = new Uint8Array(buffer)
    const params = { linearUnit: 'millimeter', linearDeflectionType: 'bounding_box_ratio', linearDeflection: 0.001, angularDeflection: 0.5 }
    const res = format === 'iges' ? occt.ReadIgesFile(content, params) : occt.ReadStepFile(content, params)
    if (!res || !res.success) {
      self.postMessage({ ok: false, error: '檔案解析失敗（可能不是有效的 STEP／IGES 檔）' })
      return
    }
    const transfer = []
    const meshes = res.meshes.map((m) => {
      const position = new Float32Array(m.attributes.position.array)
      const normal = m.attributes.normal ? new Float32Array(m.attributes.normal.array) : null
      const index = new Uint32Array(m.index.array)
      transfer.push(position.buffer, index.buffer)
      if (normal) transfer.push(normal.buffer)
      return { name: m.name, color: m.color || null, position, normal, index }
    })
    self.postMessage({ ok: true, meshes }, transfer)
  } catch (e) {
    self.postMessage({ ok: false, error: `解析元件載入失敗：${e?.message || e}` })
  }
}
