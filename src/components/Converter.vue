<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { Upload, FileImage, Download, X, CheckCircle, Loader2, AlertTriangle, Lock, Unlock } from 'lucide-vue-next'

interface UploadedFile {
  id: string
  file: File
  preview: string
  status: 'pending' | 'converting' | 'done' | 'error'
  width: number
  height: number
  dpi: number
  dpiSource: 'png' | 'jfif' | 'exif' | 'default'
  cmykData?: string
}

type PrintProfileKey = 'fogra51' | 'japan2011'
type RenderingIntentKey = 'perceptual' | 'relative_colorimetric'

interface PrintProfile {
  key: PrintProfileKey
  label: string
  condition: string
  help: string
  iccPath?: string
  tac: number
  maxBlack: number
  gcr: number
  neutralGcr: number
  blackStart: number
  gamutCompression: number
}

interface RenderingIntentOption {
  key: RenderingIntentKey
  label: string
  help: string
}

const A4_WIDTH_MM = 210
const DEFAULT_DPI = 300
const ASSUMED_SOURCE_DPI = 72
const DEFAULT_BLEED_MM = 3
const CROP_MARK_MM = 3
const CROP_LINE_MM = 0.25
const MM_PER_INCH = 25.4
const allowedTypes = ['image/png', 'image/jpeg']
const PRINT_PROFILES: Record<PrintProfileKey, PrintProfile> = {
  fogra51: {
    key: 'fogra51',
    label: 'FOGRA51 / PSO Coated v3',
    condition: '铜版纸/高级涂布纸胶印，最大总墨量 300%',
    help: '适合常见商业印刷、画册、海报、宣传单等涂布纸印刷；当前会优先保持原图观感，再控制油墨总量。',
    iccPath: '/icc/pso-coated_v3/PSOcoated_v3.icc',
    tac: 3,
    maxBlack: 0.96,
    gcr: 0.52,
    neutralGcr: 0.9,
    blackStart: 0.02,
    gamutCompression: 0.045
  },
  japan2011: {
    key: 'japan2011',
    label: 'Japan Color 2011 Coated',
    condition: '日本标准涂布纸胶印，最大总墨量 350%',
    help: '适合明确要求 Japan Color 2011 的印刷厂；总墨量更高，部分图片可能比 FOGRA51 更重或更暗。',
    iccPath: '/icc/JapanColor2011Coated/JapanColor2011Coated.icc',
    tac: 3.5,
    maxBlack: 0.8,
    gcr: 0.46,
    neutralGcr: 0.78,
    blackStart: 0.025,
    gamutCompression: 0.035
  }
}
const RENDERING_INTENTS: Record<RenderingIntentKey, RenderingIntentOption> = {
  perceptual: {
    key: 'perceptual',
    label: '感知法',
    help: '推荐用于 AI 图、照片、插画和高饱和图片，会优先保持整体观感和渐变关系。'
  },
  relative_colorimetric: {
    key: 'relative_colorimetric',
    label: '相对比色法',
    help: '适合产品图、品牌色等更重视准确色的图片；超出印刷色域的颜色可能被直接压到边界。'
  }
}

const files = ref<UploadedFile[]>([])
const isDragging = ref(false)
const isConverting = ref(false)
const isGeneratingImage = ref(false)
const conversionError = ref('')
const generatedPdf = ref<Blob | null>(null)
const generatedPdfProfile = ref<PrintProfileKey | null>(null)
const printWidth = ref(A4_WIDTH_MM)
const printHeight = ref(297)
const printDpi = ref(DEFAULT_DPI)
const bleed = ref(DEFAULT_BLEED_MM)
const lockAspectRatio = ref(true)
const bleedPreview = ref('')
const selectedPrintProfile = ref<PrintProfileKey>('fogra51')
const selectedRenderingIntent = ref<RenderingIntentKey>('perceptual')
const CMYK_API_URL = 'http://127.0.0.1:8787/api/convert-cmyk-pdf'

const selectedFile = computed(() => files.value[0])
const hasFiles = computed(() => Boolean(selectedFile.value))
const allDone = computed(() => Boolean(selectedFile.value && selectedFile.value.status === 'done'))
const activePrintProfile = computed(() => PRINT_PROFILES[selectedPrintProfile.value])
const activeRenderingIntent = computed(() => RENDERING_INTENTS[selectedRenderingIntent.value])
const hasGeneratedPdf = computed(() => Boolean(generatedPdf.value))
const aspectRatio = computed(() => {
  const file = selectedFile.value
  return file ? file.width / file.height : A4_WIDTH_MM / 297
})
const maxPrintableSize = computed(() => {
  const file = selectedFile.value
  if (!file) return { width: 0, height: 0 }

  return {
    width: Number(((file.width / printDpi.value) * MM_PER_INCH).toFixed(1)),
    height: Number(((file.height / printDpi.value) * MM_PER_INCH).toFixed(1))
  }
})
const requiredPixels = computed(() => ({
  width: Math.round((printWidth.value / MM_PER_INCH) * printDpi.value),
  height: Math.round((printHeight.value / MM_PER_INCH) * printDpi.value)
}))
const outputPixels = computed(() => ({
  width: Math.ceil(((printWidth.value + (bleed.value + CROP_MARK_MM) * 2) / MM_PER_INCH) * printDpi.value),
  height: Math.ceil(((printHeight.value + (bleed.value + CROP_MARK_MM) * 2) / MM_PER_INCH) * printDpi.value)
}))
const printPreviewStyle = computed(() => {
  const pageWidth = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const pageHeight = printHeight.value + (bleed.value + CROP_MARK_MM) * 2

  return {
    '--page-ratio': `${pageWidth} / ${pageHeight}`
  }
})
const hasResolutionWarning = computed(() => {
  const file = selectedFile.value
  if (!file) return false
  return file.width < requiredPixels.value.width || file.height < requiredPixels.value.height
})

function generateId() {
  return Math.random().toString(36).substring(2, 9)
}

function formatFileSize(size: number) {
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function formatDpi(file: UploadedFile) {
  return file.dpiSource !== 'default'
    ? `${Math.round(file.dpi)} DPI`
    : `${ASSUMED_SOURCE_DPI} DPI（默认估算）`
}

function formatDpiNote(file: UploadedFile) {
  if (file.dpiSource === 'png') return '已从 PNG pHYs 元数据读取真实 DPI。'
  if (file.dpiSource === 'jfif') return '已从 JPG JFIF 元数据读取真实 DPI。'
  if (file.dpiSource === 'exif') return '已从 JPG EXIF 元数据读取真实 DPI。'
  return '这张图片没有写入 DPI 元数据，已按常见屏幕图片的 72 DPI 估算；下方印刷尺寸仍按 300 DPI 计算。'
}

function handleDragOver(e: DragEvent) {
  e.preventDefault()
  isDragging.value = true
}

function handleDragLeave() {
  isDragging.value = false
}

function handleDrop(e: DragEvent) {
  e.preventDefault()
  isDragging.value = false
  const droppedFiles = e.dataTransfer?.files
  if (droppedFiles) {
    addFiles(droppedFiles)
  }
}

function handleFileInput(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files) {
    addFiles(target.files)
  }
  target.value = ''
}

function isAllowedImage(file: File) {
  return allowedTypes.includes(file.type)
}

async function addFiles(fileList: FileList) {
  const file = Array.from(fileList).find(isAllowedImage)
  if (!file) return

  const preview = await readFileAsDataUrl(file)
  const dimensions = await getImageDimensions(preview)
  const embeddedDpi = await readImageDpi(file)

  files.value = [{
    id: generateId(),
    file,
    preview,
    status: 'pending',
    width: dimensions.width,
    height: dimensions.height,
    dpi: embeddedDpi?.value ? Math.round(embeddedDpi.value) : ASSUMED_SOURCE_DPI,
    dpiSource: embeddedDpi?.source || 'default'
  }]

  setDefaultPrintSize()
}

function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = e => resolve(e.target?.result as string)
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

function getImageDimensions(src: string): Promise<{ width: number; height: number }> {
  return new Promise(resolve => {
    const img = new Image()
    img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight })
    img.onerror = () => resolve({ width: 0, height: 0 })
    img.src = src
  })
}

async function readImageDpi(file: File): Promise<{ value: number; source: UploadedFile['dpiSource'] } | undefined> {
  const buffer = await file.arrayBuffer()
  if (file.type === 'image/png') {
    const dpi = readPngDpi(buffer)
    return dpi ? { value: dpi, source: 'png' } : undefined
  }
  if (file.type === 'image/jpeg') {
    return readJpegDpi(buffer)
  }
}

function readPngDpi(buffer: ArrayBuffer) {
  const view = new DataView(buffer)
  if (view.byteLength < 33) return undefined

  let offset = 8
  while (offset + 12 <= view.byteLength) {
    const length = view.getUint32(offset)
    const type = String.fromCharCode(
      view.getUint8(offset + 4),
      view.getUint8(offset + 5),
      view.getUint8(offset + 6),
      view.getUint8(offset + 7)
    )

    if (type === 'pHYs' && offset + 21 <= view.byteLength) {
      const pixelsPerMeterX = view.getUint32(offset + 8)
      const pixelsPerMeterY = view.getUint32(offset + 12)
      const unit = view.getUint8(offset + 16)
      if (unit === 1) {
        return ((pixelsPerMeterX + pixelsPerMeterY) / 2) * 0.0254
      }
    }

    offset += length + 12
  }
}

function readJpegDpi(buffer: ArrayBuffer) {
  const view = new DataView(buffer)
  if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return undefined

  let exifDpi: number | undefined

  let offset = 2
  while (offset + 4 < view.byteLength) {
    if (view.getUint8(offset) !== 0xff) break

    const marker = view.getUint8(offset + 1)
    const length = view.getUint16(offset + 2)
    if (length < 2 || offset + length + 2 > view.byteLength) break

    if (marker === 0xe0 && offset + 16 < view.byteLength) {
      const id = String.fromCharCode(
        view.getUint8(offset + 4),
        view.getUint8(offset + 5),
        view.getUint8(offset + 6),
        view.getUint8(offset + 7),
        view.getUint8(offset + 8)
      )
      if (id === 'JFIF\0') {
        const unit = view.getUint8(offset + 11)
        const xDensity = view.getUint16(offset + 12)
        const yDensity = view.getUint16(offset + 14)
        const density = (xDensity + yDensity) / 2
        if (unit === 1) return { value: density, source: 'jfif' as const }
        if (unit === 2) return { value: density * 2.54, source: 'jfif' as const }
      }
    }

    if (marker === 0xe1 && offset + 18 < view.byteLength) {
      exifDpi = readExifDpi(view, offset + 4, length - 2) || exifDpi
    }

    offset += length + 2
  }

  return exifDpi ? { value: exifDpi, source: 'exif' as const } : undefined
}

function readExifDpi(view: DataView, start: number, length: number) {
  if (length < 14 || start + length > view.byteLength) return undefined

  const exifHeader = String.fromCharCode(
    view.getUint8(start),
    view.getUint8(start + 1),
    view.getUint8(start + 2),
    view.getUint8(start + 3),
    view.getUint8(start + 4),
    view.getUint8(start + 5)
  )
  if (exifHeader !== 'Exif\0\0') return undefined

  const tiffStart = start + 6
  const byteOrder = String.fromCharCode(view.getUint8(tiffStart), view.getUint8(tiffStart + 1))
  const littleEndian = byteOrder === 'II'
  if (!littleEndian && byteOrder !== 'MM') return undefined
  if (view.getUint16(tiffStart + 2, littleEndian) !== 42) return undefined

  const ifdOffset = view.getUint32(tiffStart + 4, littleEndian)
  const ifdStart = tiffStart + ifdOffset
  if (ifdStart + 2 > start + length) return undefined

  const entryCount = view.getUint16(ifdStart, littleEndian)
  let xResolution: number | undefined
  let yResolution: number | undefined
  let resolutionUnit = 2

  for (let i = 0; i < entryCount; i++) {
    const entry = ifdStart + 2 + i * 12
    if (entry + 12 > start + length) break

    const tag = view.getUint16(entry, littleEndian)
    const type = view.getUint16(entry + 2, littleEndian)
    const count = view.getUint32(entry + 4, littleEndian)

    if ((tag === 0x011a || tag === 0x011b) && type === 5 && count >= 1) {
      const valueOffset = tiffStart + view.getUint32(entry + 8, littleEndian)
      if (valueOffset + 8 <= start + length) {
        const numerator = view.getUint32(valueOffset, littleEndian)
        const denominator = view.getUint32(valueOffset + 4, littleEndian)
        const value = denominator ? numerator / denominator : undefined
        if (tag === 0x011a) xResolution = value
        if (tag === 0x011b) yResolution = value
      }
    }

    if (tag === 0x0128 && type === 3 && count >= 1) {
      resolutionUnit = view.getUint16(entry + 8, littleEndian)
    }
  }

  if (!xResolution && !yResolution) return undefined

  const dpi = ((xResolution || yResolution || 0) + (yResolution || xResolution || 0)) / 2
  if (!dpi) return undefined
  return resolutionUnit === 3 ? dpi * 2.54 : dpi
}

function removeFile() {
  files.value = []
  bleedPreview.value = ''
  generatedPdf.value = null
  generatedPdfProfile.value = null
}

function setDefaultPrintSize() {
  printDpi.value = DEFAULT_DPI
  const file = selectedFile.value
  if (file) {
    printWidth.value = Number(((file.width / DEFAULT_DPI) * MM_PER_INCH).toFixed(1))
    printHeight.value = Number(((file.height / DEFAULT_DPI) * MM_PER_INCH).toFixed(1))
  } else {
    printWidth.value = A4_WIDTH_MM
    printHeight.value = Number((printWidth.value / aspectRatio.value).toFixed(1))
  }
  bleed.value = DEFAULT_BLEED_MM
  lockAspectRatio.value = true
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error('图片加载失败'))
    img.src = src
  })
}

function drawCover(
  ctx: CanvasRenderingContext2D,
  img: CanvasImageSource,
  x: number,
  y: number,
  width: number,
  height: number,
  sourceWidth: number,
  sourceHeight: number
) {
  const sourceRatio = sourceWidth / sourceHeight
  const targetRatio = width / height
  let sx = 0
  let sy = 0
  let sw = sourceWidth
  let sh = sourceHeight

  if (sourceRatio > targetRatio) {
    sw = sourceHeight * targetRatio
    sx = (sourceWidth - sw) / 2
  } else {
    sh = sourceWidth / targetRatio
    sy = (sourceHeight - sh) / 2
  }

  ctx.drawImage(img, sx, sy, sw, sh, x, y, width, height)
}

function drawMirroredBleed(ctx: CanvasRenderingContext2D, trimX: number, trimY: number, trimWidth: number, trimHeight: number, bleedX: number, bleedY: number) {
  ctx.save()
  ctx.translate(trimX * 2, 0)
  ctx.scale(-1, 1)
  ctx.drawImage(ctx.canvas, trimX, trimY, bleedX, trimHeight, trimX, trimY, bleedX, trimHeight)
  ctx.restore()

  ctx.save()
  ctx.translate((trimX + trimWidth) * 2, 0)
  ctx.scale(-1, 1)
  ctx.drawImage(ctx.canvas, trimX + trimWidth - bleedX, trimY, bleedX, trimHeight, trimX + trimWidth - bleedX, trimY, bleedX, trimHeight)
  ctx.restore()

  ctx.save()
  ctx.translate(0, trimY * 2)
  ctx.scale(1, -1)
  ctx.drawImage(ctx.canvas, 0, trimY, ctx.canvas.width, bleedY, 0, trimY, ctx.canvas.width, bleedY)
  ctx.restore()

  ctx.save()
  ctx.translate(0, (trimY + trimHeight) * 2)
  ctx.scale(1, -1)
  ctx.drawImage(ctx.canvas, 0, trimY + trimHeight - bleedY, ctx.canvas.width, bleedY, 0, trimY + trimHeight - bleedY, ctx.canvas.width, bleedY)
  ctx.restore()
}

async function createBleedCanvas(source: string, width: number, height: number) {
  const img = await loadImage(source)
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  const ctx = canvas.getContext('2d')!
  const pageWidthMm = printWidth.value + bleed.value * 2
  const pageHeightMm = printHeight.value + bleed.value * 2
  const bleedX = Math.max(1, Math.round((bleed.value / pageWidthMm) * width))
  const bleedY = Math.max(1, Math.round((bleed.value / pageHeightMm) * height))
  const trimX = bleedX
  const trimY = bleedY
  const trimWidth = Math.max(1, width - bleedX * 2)
  const trimHeight = Math.max(1, height - bleedY * 2)

  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.clearRect(0, 0, width, height)
  drawCover(ctx, img, trimX, trimY, trimWidth, trimHeight, img.naturalWidth, img.naturalHeight)
  drawMirroredBleed(ctx, trimX, trimY, trimWidth, trimHeight, bleedX, bleedY)
  drawCover(ctx, img, trimX, trimY, trimWidth, trimHeight, img.naturalWidth, img.naturalHeight)

  return canvas
}

function drawCropMarksOnCanvas(ctx: CanvasRenderingContext2D, scale: number, sheetWidth: number, sheetHeight: number) {
  const mark = Math.max(1, Math.round(CROP_MARK_MM * scale))
  const bleedPx = Math.max(1, Math.round(bleed.value * scale))
  const line = Math.max(1, Math.round(CROP_LINE_MM * scale))
  const trimLeft = mark + bleedPx
  const trimTop = mark + bleedPx
  const trimRight = sheetWidth - mark - bleedPx
  const trimBottom = sheetHeight - mark - bleedPx

  ctx.save()
  ctx.fillStyle = '#262626'
  ctx.fillRect(0, trimTop - Math.round(line / 2), mark, line)
  ctx.fillRect(sheetWidth - mark, trimTop - Math.round(line / 2), mark, line)
  ctx.fillRect(0, trimBottom - Math.round(line / 2), mark, line)
  ctx.fillRect(sheetWidth - mark, trimBottom - Math.round(line / 2), mark, line)
  ctx.fillRect(trimLeft - Math.round(line / 2), 0, line, mark)
  ctx.fillRect(trimRight - Math.round(line / 2), 0, line, mark)
  ctx.fillRect(trimLeft - Math.round(line / 2), sheetHeight - mark, line, mark)
  ctx.fillRect(trimRight - Math.round(line / 2), sheetHeight - mark, line, mark)
  ctx.restore()
}

async function createPrintSheetDataUrl(source: string, maxSide = 1800) {
  const sheetWidthMm = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetHeightMm = printHeight.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetRatio = sheetWidthMm / sheetHeightMm
  const sheetWidth = sheetRatio >= 1 ? maxSide : Math.max(1, Math.round(maxSide * sheetRatio))
  const sheetHeight = sheetRatio >= 1 ? Math.max(1, Math.round(maxSide / sheetRatio)) : maxSide
  const scale = sheetWidth / sheetWidthMm
  const markPx = Math.max(1, Math.round(CROP_MARK_MM * scale))
  const artworkWidth = Math.max(1, sheetWidth - markPx * 2)
  const artworkHeight = Math.max(1, sheetHeight - markPx * 2)
  const artwork = await createBleedCanvas(source, artworkWidth, artworkHeight)
  const canvas = document.createElement('canvas')
  canvas.width = sheetWidth
  canvas.height = sheetHeight

  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, sheetWidth, sheetHeight)
  ctx.drawImage(artwork, markPx, markPx)
  drawCropMarksOnCanvas(ctx, scale, sheetWidth, sheetHeight)

  return canvas.toDataURL('image/jpeg', 0.95)
}

async function createPrintSheetDataUrlAtDpi(source: string) {
  const canvas = await createPrintSheetCanvasAtDpi(source)
  return canvas.toDataURL('image/jpeg', 0.95)
}

async function createPrintSheetCanvasAtDpi(source: string) {
  const sheetWidthMm = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetHeightMm = printHeight.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetWidth = Math.ceil((sheetWidthMm / MM_PER_INCH) * printDpi.value)
  const sheetHeight = Math.ceil((sheetHeightMm / MM_PER_INCH) * printDpi.value)
  const scale = sheetWidth / sheetWidthMm
  const markPx = Math.max(1, Math.round(CROP_MARK_MM * scale))
  const artworkWidth = Math.max(1, sheetWidth - markPx * 2)
  const artworkHeight = Math.max(1, sheetHeight - markPx * 2)
  const artwork = await createBleedCanvas(source, artworkWidth, artworkHeight)
  const canvas = document.createElement('canvas')
  canvas.width = sheetWidth
  canvas.height = sheetHeight

  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, sheetWidth, sheetHeight)
  ctx.drawImage(artwork, markPx, markPx)
  drawCropMarksOnCanvas(ctx, scale, sheetWidth, sheetHeight)

  return canvas
}

async function updateBleedPreview() {
  const file = selectedFile.value
  if (!file) {
    bleedPreview.value = ''
    return
  }

  try {
    if (file.cmykData) {
      bleedPreview.value = file.cmykData
      return
    }
    bleedPreview.value = await createPrintSheetDataUrl(file.preview, 1200)
  } catch (error) {
    bleedPreview.value = file.cmykData || file.preview
  }
}

function updateHeightFromWidth() {
  if (!lockAspectRatio.value) return
  printHeight.value = Number((printWidth.value / aspectRatio.value).toFixed(1))
}

function updateWidthFromHeight() {
  if (!lockAspectRatio.value) return
  printWidth.value = Number((printHeight.value * aspectRatio.value).toFixed(1))
}

function toggleAspectRatioLock() {
  lockAspectRatio.value = !lockAspectRatio.value
  if (lockAspectRatio.value) {
    updateHeightFromWidth()
  }
}

function clamp(value: number, min = 0, max = 1) {
  return Math.min(max, Math.max(min, value))
}

function rgbToHsl(r: number, g: number, b: number) {
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const maxRgb = Math.max(rn, gn, bn)
  const minRgb = Math.min(rn, gn, bn)
  const chroma = maxRgb - minRgb
  const lightness = (maxRgb + minRgb) / 2

  if (chroma === 0) {
    return { h: 0, s: 0, l: lightness }
  }

  let hue = 0
  if (maxRgb === rn) {
    hue = ((gn - bn) / chroma) % 6
  } else if (maxRgb === gn) {
    hue = (bn - rn) / chroma + 2
  } else {
    hue = (rn - gn) / chroma + 4
  }
  hue = (hue * 60 + 360) % 360

  return {
    h: hue,
    s: chroma / (1 - Math.abs(2 * lightness - 1)),
    l: lightness
  }
}

function hslToRgb(h: number, s: number, l: number): [number, number, number] {
  const chroma = (1 - Math.abs(2 * l - 1)) * s
  const x = chroma * (1 - Math.abs(((h / 60) % 2) - 1))
  const match = l - chroma / 2
  let rr = 0
  let gg = 0
  let bb = 0

  if (h < 60) {
    rr = chroma
    gg = x
  } else if (h < 120) {
    rr = x
    gg = chroma
  } else if (h < 180) {
    gg = chroma
    bb = x
  } else if (h < 240) {
    gg = x
    bb = chroma
  } else if (h < 300) {
    rr = x
    bb = chroma
  } else {
    rr = chroma
    bb = x
  }

  return [
    Math.round(clamp(rr + match) * 255),
    Math.round(clamp(gg + match) * 255),
    Math.round(clamp(bb + match) * 255)
  ]
}

function isHueBetween(hue: number, start: number, end: number) {
  return start <= end ? hue >= start && hue <= end : hue >= start || hue <= end
}

function compressRgbForPrintGamut(r: number, g: number, b: number, profile: PrintProfile): [number, number, number] {
  const { h, s, l } = rgbToHsl(r, g, b)
  if (s < 0.72) return [r, g, b]

  const vividness = clamp((s - 0.72) / 0.28)
  const highlight = clamp((l - 0.65) / 0.35)
  let saturation = s
  let lightness = l

  if (isHueBetween(h, 80, 170)) {
    saturation *= 1 - profile.gamutCompression * (0.8 + vividness * 0.45)
  } else if (isHueBetween(h, 175, 265)) {
    saturation *= 1 - profile.gamutCompression * (1 + vividness * 0.55)
    lightness *= 1 - 0.025 * vividness - 0.015 * highlight
  } else if (isHueBetween(h, 285, 340)) {
    saturation *= 1 - profile.gamutCompression * (0.55 + vividness * 0.35)
  } else if (isHueBetween(h, 350, 35)) {
    saturation *= 1 - profile.gamutCompression * 0.25 * vividness
  } else if (isHueBetween(h, 35, 75)) {
    saturation *= 1 - profile.gamutCompression * 0.2 * vividness
  }

  return hslToRgb(h, clamp(saturation), clamp(lightness, 0.02, 0.98))
}

function limitTotalInk(c: number, m: number, y: number, k: number, totalInkLimit: number): [number, number, number, number] {
  const totalInk = c + m + y + k
  if (totalInk > totalInkLimit) {
    const scale = Math.max(0, (totalInkLimit - k) / Math.max(0.0001, c + m + y))
    c *= scale
    m *= scale
    y *= scale
  }

  return [c, m, y, k]
}

function rgbToPrintCmykBytes(r: number, g: number, b: number, profile = activePrintProfile.value): [number, number, number, number] {
  ;[r, g, b] = compressRgbForPrintGamut(r, g, b, profile)
  const rn = r / 255
  const gn = g / 255
  const bn = b / 255
  const { s } = rgbToHsl(r, g, b)
  const luminance = 0.2126 * rn + 0.7152 * gn + 0.0722 * bn
  const c0 = 1 - rn
  const m0 = 1 - gn
  const y0 = 1 - bn
  const sharedInk = Math.min(c0, m0, y0)
  const neutral = Math.max(rn, gn, bn) - Math.min(rn, gn, bn) < 0.025

  if (sharedInk < 0.003 && luminance > 0.985) {
    return [0, 0, 0, 0]
  }

  const blackEligible = clamp((sharedInk - profile.blackStart) / (1 - profile.blackStart))
  const colorPenalty = neutral ? 0 : s * 0.28
  const blackRatio = clamp((neutral ? profile.neutralGcr : profile.gcr) - colorPenalty, 0.08, 0.92)
  let k = clamp(sharedInk * blackEligible * blackRatio, 0, profile.maxBlack)
  const divider = Math.max(0.0001, 1 - k)
  let c = clamp((c0 - k) / divider)
  let m = clamp((m0 - k) / divider)
  let y = clamp((y0 - k) / divider)

  if (neutral && luminance < 0.96) {
    const grayInk = clamp((c + m + y) / 3)
    c = clamp(grayInk)
    m = clamp(grayInk)
    y = clamp(grayInk * 0.98)
  }

  ;[c, m, y, k] = limitTotalInk(c, m, y, k, profile.tac)

  return [
    Math.round(clamp(c) * 255),
    Math.round(clamp(m) * 255),
    Math.round(clamp(y) * 255),
    Math.round(clamp(k) * 255)
  ]
}

function canvasToCmykBytes(canvas: HTMLCanvasElement, profile = activePrintProfile.value) {
  const ctx = canvas.getContext('2d')!
  const rgba = ctx.getImageData(0, 0, canvas.width, canvas.height).data
  const cmyk = new Uint8Array(canvas.width * canvas.height * 4)

  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 4) {
    const alpha = rgba[i + 3] / 255
    const r = Math.round(rgba[i] * alpha + 255 * (1 - alpha))
    const g = Math.round(rgba[i + 1] * alpha + 255 * (1 - alpha))
    const b = Math.round(rgba[i + 2] * alpha + 255 * (1 - alpha))
    const [c, m, y, k] = rgbToPrintCmykBytes(r, g, b, profile)
    cmyk[j] = c
    cmyk[j + 1] = m
    cmyk[j + 2] = y
    cmyk[j + 3] = k
  }

  return cmyk
}

function ascii(value: string) {
  return new TextEncoder().encode(value)
}

function pdfString(value: string) {
  return value.replace(/[()\\]/g, match => `\\${match}`)
}

async function loadIccProfile(profile: PrintProfile) {
  if (!profile.iccPath) return undefined
  if (iccCache.has(profile.iccPath)) return iccCache.get(profile.iccPath)

  const response = await fetch(profile.iccPath)
  if (!response.ok) throw new Error(`无法加载 ICC profile: ${profile.label}`)
  const bytes = new Uint8Array(await response.arrayBuffer())
  iccCache.set(profile.iccPath, bytes)
  return bytes
}

function buildCmykPdf(
  imageBytes: Uint8Array,
  imageWidth: number,
  imageHeight: number,
  pageWidthMm: number,
  pageHeightMm: number,
  profile: PrintProfile,
  iccBytes?: Uint8Array
) {
  const pageWidthPt = (pageWidthMm / MM_PER_INCH) * 72
  const pageHeightPt = (pageHeightMm / MM_PER_INCH) * 72
  const chunks: Uint8Array[] = []
  const offsets: number[] = [0]
  let position = 0

  function push(chunk: string | Uint8Array) {
    const bytes = typeof chunk === 'string' ? ascii(chunk) : chunk
    chunks.push(bytes)
    position += bytes.length
  }

  function object(parts: Array<string | Uint8Array>) {
    const id = offsets.length
    offsets.push(position)
    push(`${id} 0 obj\n`)
    for (const part of parts) push(part)
    push('\nendobj\n')
    return id
  }

  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
  object([`<< /Type /Catalog /Pages 2 0 R${iccBytes ? ' /OutputIntents [6 0 R]' : ''} >>`])
  object(['<< /Type /Pages /Kids [3 0 R] /Count 1 >>'])
  object([`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidthPt.toFixed(3)} ${pageHeightPt.toFixed(3)}] /Resources << /XObject << /Im1 4 0 R >> >> /Contents 5 0 R >>`])
  object([
    `<< /Type /XObject /Subtype /Image /Width ${imageWidth} /Height ${imageHeight} /ColorSpace ${iccBytes ? '[/ICCBased 7 0 R]' : '/DeviceCMYK'} /BitsPerComponent 8 /Length ${imageBytes.length} >>\nstream\n`,
    imageBytes,
    '\nendstream'
  ])

  const content = `q\n${pageWidthPt.toFixed(3)} 0 0 ${pageHeightPt.toFixed(3)} 0 0 cm\n/Im1 Do\nQ\n`
  object([`<< /Length ${ascii(content).length} >>\nstream\n${content}endstream`])

  if (iccBytes) {
    object([`<< /Type /OutputIntent /S /GTS_PDFX /OutputConditionIdentifier (${pdfString(profile.label)}) /Info (${pdfString(profile.condition)}) /DestOutputProfile 7 0 R >>`])
    object([`<< /N 4 /Alternate /DeviceCMYK /Length ${iccBytes.length} >>\nstream\n`, iccBytes, '\nendstream'])
  }

  const xrefOffset = position
  push(`xref\n0 ${offsets.length}\n`)
  push('0000000000 65535 f \n')
  for (let i = 1; i < offsets.length; i++) {
    push(`${String(offsets[i]).padStart(10, '0')} 00000 n \n`)
  }
  push(`trailer\n<< /Size ${offsets.length} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`)

  return new Blob(chunks, { type: 'application/pdf' })
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function canvasToJpegBlob(canvas: HTMLCanvasElement, quality = 0.98): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(blob => {
      if (blob) {
        resolve(blob)
      } else {
        reject(new Error('无法导出印刷页面图像'))
      }
    }, 'image/jpeg', quality)
  })
}

async function convertToCMYK(uploadedFile: UploadedFile): Promise<string> {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = img.width
        canvas.height = img.height
        const ctx = canvas.getContext('2d')!

        ctx.drawImage(img, 0, 0)
        resolve(canvas.toDataURL('image/jpeg', 0.95))
      } catch (error) {
        reject(error)
      }
    }
    img.onerror = () => reject(new Error('图片加载失败'))
    img.src = uploadedFile.preview
  })
}

async function startConversion() {
  const file = selectedFile.value
  if (!file) return

  isConverting.value = true
  conversionError.value = ''
  generatedPdf.value = null
  generatedPdfProfile.value = null
  file.status = 'converting'

  try {
    await new Promise(r => setTimeout(r, 800))
    const printImage = await createPrintSheetDataUrl(file.preview, 2200)
    file.cmykData = await convertToCMYK({ ...file, preview: printImage })
    await updateBleedPreview()
    generatedPdf.value = await createCmykPdfBlob(file)
    generatedPdfProfile.value = selectedPrintProfile.value
    file.status = 'done'
  } catch (error) {
    file.status = 'error'
    const detail = error instanceof Error ? error.message : ''
    if (detail) {
      conversionError.value = `ICC CMYK 转换失败：${detail}`
      isConverting.value = false
      return
    }
    conversionError.value = 'PDF 生成失败，请尝试减小印刷尺寸或降低 DPI 后重新转换。'
  }

  isConverting.value = false
}

async function createCmykPdfBlob(file: UploadedFile) {
  await ensureCmykServiceReady()

  const formData = new FormData()
  formData.append('image', file.file, file.file.name)
  formData.append('profile', selectedPrintProfile.value)
  formData.append('renderingIntent', selectedRenderingIntent.value)
  formData.append('printWidthMm', String(printWidth.value))
  formData.append('printHeightMm', String(printHeight.value))
  formData.append('dpi', String(printDpi.value))
  formData.append('bleedMm', String(bleed.value))
  formData.append('cropMarkMm', String(CROP_MARK_MM))

  const response = await fetch(CMYK_API_URL, {
    method: 'POST',
    body: formData
  })

  if (!response.ok) {
    const message = await response.text().catch(() => '')
    if (message.includes('Invalid page size')) {
      throw new Error('本地 CMYK 转换服务仍是旧版本，请停止后重新运行 npm.cmd run convert-server。')
    }
    throw new Error(message || 'ICC CMYK 转换服务不可用')
  }

  return response.blob()
}

async function ensureCmykServiceReady() {
  try {
    const healthUrl = CMYK_API_URL.replace('/api/convert-cmyk-pdf', '/health')
    const response = await fetch(healthUrl, { cache: 'no-store' })
    const status = await response.json()
    if (!status?.supportsOriginalImagePdf) {
      throw new Error('本地 CMYK 转换服务仍是旧版本，请停止后重新运行 npm.cmd run convert-server。')
    }
  } catch (error) {
    if (error instanceof Error && error.message.includes('旧版本')) throw error
    throw new Error('无法连接本地 CMYK 转换服务，请确认 npm.cmd run convert-server 正在运行。')
  }
}

function downloadPDF() {
  if (isConverting.value) return
  if (!generatedPdf.value) {
    conversionError.value = '请先生成 PDF 文件，再下载。'
    return
  }

  downloadBlob(generatedPdf.value, 'printable-cmyk.pdf')
}

async function downloadPrintImage() {
  const file = selectedFile.value
  if (!file) return

  isGeneratingImage.value = true
  try {
    const printImage = await createPrintSheetDataUrlAtDpi(file.preview)
    const finalImage = await convertToCMYK({ ...file, preview: printImage })
    const link = document.createElement('a')
    link.href = finalImage
    link.download = 'printable-high-resolution.jpg'
    link.click()
  } finally {
    isGeneratingImage.value = false
  }
}

watch(
  [selectedFile, printWidth, printHeight, printDpi, bleed, selectedPrintProfile, selectedRenderingIntent],
  () => {
    if (!isConverting.value) {
      generatedPdf.value = null
      generatedPdfProfile.value = null
      if (selectedFile.value?.status === 'done') {
        selectedFile.value.status = 'pending'
      }
    }
    updateBleedPreview()
  },
  { flush: 'post' }
)
</script>

<template>
  <section id="converter" class="py-20 px-6 md:px-12 bg-secondary">
    <div class="max-w-4xl mx-auto">
      <div class="text-center mb-12">
        <h2 class="text-3xl md:text-4xl font-serif font-medium text-foreground">
          上传您的图片
        </h2>
        <p class="mt-4 text-muted-foreground">
          支持 PNG、JPG 格式
        </p>
      </div>

      <div
        class="drop-zone border-2 border-dashed border-border rounded-2xl bg-card transition-all cursor-pointer"
        :class="{ 'dragging': isDragging, 'p-12 text-center': !hasFiles, 'p-4': hasFiles }"
        @dragover="handleDragOver"
        @dragleave="handleDragLeave"
        @drop="handleDrop"
        @click="($refs.fileInput as HTMLInputElement).click()"
      >
        <input
          ref="fileInput"
          type="file"
          accept=".png,.jpg,.jpeg,image/png,image/jpeg"
          class="hidden"
          @change="handleFileInput"
        />

        <div v-if="!selectedFile" class="flex flex-col items-center gap-4">
          <div class="w-16 h-16 bg-secondary rounded-2xl flex items-center justify-center">
            <Upload class="w-7 h-7 text-muted-foreground" />
          </div>
          <div>
            <p class="text-lg font-medium text-foreground">
              拖拽RGB图片到此处，或点击上传
            </p>
            <p class="mt-1 text-sm text-muted-foreground">
              支持 PNG、JPG 格式
            </p>
          </div>
        </div>

        <div v-else class="flex flex-col gap-4 md:flex-row md:items-center">
          <div class="aspect-[4/3] w-full overflow-hidden rounded-xl bg-secondary md:w-56">
            <img
              :src="selectedFile.cmykData || selectedFile.preview"
              :alt="selectedFile.file.name"
              class="h-full w-full object-contain"
            />
          </div>

          <div class="min-w-0 flex-1 text-left">
            <p class="truncate text-lg font-medium text-foreground">{{ selectedFile.file.name }}</p>
            <div class="mt-3 grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
              <p>文件大小：{{ formatFileSize(selectedFile.file.size) }}</p>
              <p>分辨率：{{ selectedFile.width }} x {{ selectedFile.height }} px</p>
              <p>DPI：{{ formatDpi(selectedFile) }}</p>
              <p>格式：{{ selectedFile.file.type === 'image/png' ? 'PNG' : 'JPG' }}</p>
            </div>
            <p class="mt-3 text-xs text-muted-foreground">
              {{ formatDpiNote(selectedFile) }}
            </p>
          </div>

          <div class="flex items-center gap-3 md:self-center">
            <div v-if="selectedFile.status === 'pending'" class="text-sm text-muted-foreground">
              等待转换
            </div>
            <div v-else-if="selectedFile.status === 'converting'" class="flex items-center gap-2 text-accent">
              <Loader2 class="w-4 h-4 animate-spin" />
              <span class="text-sm">转换中...</span>
            </div>
            <div v-else-if="selectedFile.status === 'done'" class="flex items-center gap-2 text-green-600">
              <CheckCircle class="w-4 h-4" />
              <span class="text-sm">已完成</span>
            </div>
            <div v-else-if="selectedFile.status === 'error'" class="text-sm text-accent">
              转换失败
            </div>

            <button
              @click.stop="removeFile"
              class="w-8 h-8 rounded-lg bg-secondary flex items-center justify-center hover:bg-muted transition-colors"
              aria-label="移除图片"
            >
              <X class="w-4 h-4 text-muted-foreground" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="selectedFile" class="mt-6 rounded-2xl border border-border bg-card p-5">
        <div class="grid gap-8 lg:grid-cols-[minmax(0,1.05fr)_minmax(280px,0.95fr)] lg:items-start">
          <div>
            <div>
              <div>
                <h3 class="text-xl font-serif font-medium text-foreground">印刷尺寸</h3>
                <p class="mt-1 text-sm text-muted-foreground">
                  当前图片在 {{ printDpi }} DPI 下最大建议尺寸：{{ maxPrintableSize.width }} x {{ maxPrintableSize.height }} mm
                </p>
              </div>
              <button
                @click="toggleAspectRatioLock"
                class="mt-3 inline-flex items-center gap-1.5 rounded-lg bg-secondary px-2.5 py-1.5 text-xs font-medium text-foreground hover:bg-muted transition-colors"
              >
                <Lock v-if="lockAspectRatio" class="h-3.5 w-3.5" />
                <Unlock v-else class="h-3.5 w-3.5" />
                {{ lockAspectRatio ? '锁定比例' : '自由尺寸' }}
              </button>
            </div>

            <div class="mt-5 grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span class="text-sm font-medium text-foreground">宽度 (mm)</span>
                <input
                  v-model.number="printWidth"
                  @input="updateHeightFromWidth"
                  type="number"
                  min="1"
                  step="0.1"
                  class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
                />
              </label>

              <label class="block">
                <span class="text-sm font-medium text-foreground">高度 (mm)</span>
                <input
                  v-model.number="printHeight"
                  @input="updateWidthFromHeight"
                  type="number"
                  min="1"
                  step="0.1"
                  class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
                />
              </label>
            </div>

            <div class="mt-4 grid gap-4 sm:grid-cols-2">
              <label class="block">
                <span class="text-sm font-medium text-foreground">DPI</span>
                <input
                  v-model.number="printDpi"
                  type="number"
                  min="1"
                  step="1"
                  class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
                />
              </label>

              <label class="block">
                <span class="text-sm font-medium text-foreground">出血 (mm)</span>
                <input
                  v-model.number="bleed"
                  type="number"
                  min="0"
                  step="0.1"
                  class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
                />
              </label>
            </div>

            <label class="mt-4 block">
              <span class="text-sm font-medium text-foreground">CMYK 印刷配置</span>
              <select
                v-model="selectedPrintProfile"
                class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
              >
                <option
                  v-for="profile in PRINT_PROFILES"
                  :key="profile.key"
                  :value="profile.key"
                >
                  {{ profile.label }}
                </option>
              </select>
              <span class="mt-2 block text-xs text-muted-foreground">
                {{ activePrintProfile.condition }}
              </span>
              <span class="mt-1 block text-xs text-muted-foreground">
                {{ activePrintProfile.help }}
              </span>
            </label>

            <label class="mt-4 block">
              <span class="text-sm font-medium text-foreground">渲染意图</span>
              <select
                v-model="selectedRenderingIntent"
                class="mt-2 w-full rounded-xl border border-border bg-background px-4 py-3 text-foreground outline-none focus:border-primary"
              >
                <option
                  v-for="intent in RENDERING_INTENTS"
                  :key="intent.key"
                  :value="intent.key"
                >
                  {{ intent.label }}
                </option>
              </select>
              <span class="mt-2 block text-xs text-muted-foreground">
                {{ activeRenderingIntent.help }}
              </span>
              <span class="mt-1 block text-xs text-muted-foreground">
                源 RGB 会优先使用原图嵌入 ICC；没有 ICC 时按 sRGB 处理。
              </span>
            </label>

            <div class="mt-5 rounded-xl bg-secondary p-4 text-sm text-muted-foreground">
              成品区域像素需求：{{ requiredPixels.width }} x {{ requiredPixels.height }} px
              <span class="block mt-1">导出文件像素：{{ outputPixels.width }} x {{ outputPixels.height }} px，包含 {{ bleed }}mm 出血和裁切参考线。</span>
            </div>

            <div
              v-if="hasResolutionWarning"
              class="mt-4 rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm text-foreground"
            >
              <div class="flex gap-2">
                <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" />
                <div>
                  <p class="font-medium">图片分辨率不足</p>
                  <p class="mt-1 text-muted-foreground">
                    当前图片不足以让成品裁切区域在所选尺寸和 DPI 下保持足够清晰度，建议减小印刷尺寸、降低 DPI 或上传更高分辨率图片。
                  </p>
                </div>
              </div>
            </div>

            <div
              v-if="conversionError"
              class="mt-4 rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm text-foreground"
            >
              <div class="flex gap-2">
                <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" />
                <p>{{ conversionError }}</p>
              </div>
            </div>
          </div>

          <div>
            <div class="flex items-start justify-between gap-4">
              <div>
                <h3 class="text-xl font-serif font-medium text-foreground">印刷文件预览</h3>
                <p class="mt-1 text-sm text-muted-foreground">
                  已从原图边缘镜像补全 {{ bleed }}mm 出血，裁切参考线完全位于出血图片外侧。
                </p>
              </div>
            </div>

            <div class="mt-5 rounded-2xl bg-secondary p-5">
              <div
                class="print-preview relative mx-auto w-full max-w-sm overflow-hidden bg-white shadow-lg"
                :style="printPreviewStyle"
              >
                <img
                  :src="bleedPreview || selectedFile.cmykData || selectedFile.preview"
                  :alt="selectedFile.file.name"
                  class="absolute inset-0 h-full w-full object-cover"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="hasFiles" class="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
        <button
          @click="downloadPrintImage"
          :disabled="isGeneratingImage || isConverting"
          class="btn-primary bg-accent text-accent-foreground px-8 py-4 rounded-xl text-base font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto justify-center"
        >
          <template v-if="isGeneratingImage">
            <Loader2 class="w-5 h-5 animate-spin" />
            生成中...
          </template>
          <template v-else>
            <Download class="w-5 h-5" />
            生成高清印刷图片
          </template>
        </button>

        <button
          @click="startConversion"
          :disabled="isConverting"
          class="btn-primary bg-primary text-primary-foreground px-8 py-4 rounded-xl text-base font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto justify-center"
        >
          <template v-if="isConverting">
            <Loader2 class="w-5 h-5 animate-spin" />
            转换中...
          </template>
          <template v-else>
            <FileImage class="w-5 h-5" />
            转换为CMYK文件
          </template>
        </button>

        <button
          @click="downloadPDF"
          :disabled="!hasGeneratedPdf || isConverting"
          class="btn-primary bg-accent text-accent-foreground px-8 py-4 rounded-xl text-base font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto justify-center"
        >
          <Download class="w-5 h-5" />
          下载 PDF 文件
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.print-preview {
  aspect-ratio: var(--page-ratio);
}
</style>
