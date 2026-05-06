<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { Upload, FileImage, Download, X, CheckCircle, Loader2, AlertTriangle, Lock, Unlock, Sparkles } from 'lucide-vue-next'

interface UploadedFile {
  id: string
  file: File
  preview: string
  aiBleedPreview?: string
  aiBleedFile?: File
  aiBleedWidth?: number
  aiBleedHeight?: number
  status: 'pending' | 'converting' | 'done' | 'error'
  width: number
  height: number
  dpi: number
  dpiSource: 'png' | 'jfif' | 'exif' | 'default'
  cmykData?: string
}

type PrintProfileKey = 'fogra51' | 'japan2011'
type RenderingIntentKey = 'perceptual' | 'relative_colorimetric'
type UpscaleResolution = '2k' | '4k'
type CropResizeEdge = 'n' | 's' | 'e' | 'w' | 'nw' | 'ne' | 'sw' | 'se'

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
const isGeneratingBleed = ref(false)
const isApplyingAiCrop = ref(false)
const isUpscaleModalOpen = ref(false)
const isAiCropModalOpen = ref(false)
const selectedUpscaleResolution = ref<UpscaleResolution>('2k')
const selectedBleedResolution = ref<UpscaleResolution>('2k')
const upscaleError = ref('')
const bleedGenerationError = ref('')
const upscaleTaskId = ref('')
const bleedTaskId = ref('')
const upscalePollingStatus = ref('')
const bleedPollingStatus = ref('')
const pendingAiCropPreview = ref('')
const cropImageRef = ref<HTMLImageElement | null>(null)
const cropRect = ref({ x: 0, y: 0, width: 100, height: 100 })
const cropDragStart = ref<{
  pointerId: number
  mode: 'move' | 'resize'
  edge?: CropResizeEdge
  startX: number
  startY: number
  rect: { x: number; y: number; width: number; height: number }
} | null>(null)
const conversionError = ref('')
const generatedPdf = ref<Blob | null>(null)
const generatedPdfProfile = ref<PrintProfileKey | null>(null)
const printWidth = ref(A4_WIDTH_MM)
const printHeight = ref(297)
const printDpi = ref(DEFAULT_DPI)
const bleed = ref(DEFAULT_BLEED_MM)
const lockAspectRatio = ref(true)
const bleedPreview = ref('')
const bleedPreviewVersion = ref(0)
const selectedPrintProfile = ref<PrintProfileKey>('fogra51')
const selectedRenderingIntent = ref<RenderingIntentKey>('perceptual')
const CMYK_API_URL = 'http://127.0.0.1:8787/api/convert-cmyk-pdf'
const UPSCALE_API_URL = 'http://127.0.0.1:8787/api/upscale-image'
const UPSCALE_STATUS_URL = 'http://127.0.0.1:8787/api/upscale-status'
const IMAGE_PROXY_URL = 'http://127.0.0.1:8787/api/proxy-image'
const UPSCALE_POLL_INTERVAL_MS = 20_000
const UPSCALE_MAX_WAIT_MS = 10 * 60 * 1000
const UPSCALE_STATUS_TIMEOUT_MS = 30_000
const UPSCALE_MAX_CONSECUTIVE_POLL_ERRORS = 5
const UPSCALE_OPTIONS: Array<{ key: UpscaleResolution; label: string; pixels: string }> = [
  { key: '2k', label: '2K', pixels: '约 2048 px 级' },
  { key: '4k', label: '4K', pixels: '约 4096 px 级' }
]

const selectedFile = computed(() => files.value[0])
const hasFiles = computed(() => Boolean(selectedFile.value))
const allDone = computed(() => Boolean(selectedFile.value && selectedFile.value.status === 'done'))
const activePrintProfile = computed(() => PRINT_PROFILES[selectedPrintProfile.value])
const activeRenderingIntent = computed(() => RENDERING_INTENTS[selectedRenderingIntent.value])
const hasGeneratedPdf = computed(() => Boolean(generatedPdf.value))
const printPreviewImageSrc = computed(() => {
  const file = selectedFile.value
  return bleedPreview.value || file?.cmykData || file?.aiBleedPreview || file?.preview || ''
})
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
const bleedArtworkPixels = computed(() => ({
  width: Math.ceil(((printWidth.value + bleed.value * 2) / MM_PER_INCH) * printDpi.value),
  height: Math.ceil(((printHeight.value + bleed.value * 2) / MM_PER_INCH) * printDpi.value)
}))
const aiBleedPixelsLabel = computed(() => {
  const file = selectedFile.value
  if (!file?.aiBleedWidth || !file.aiBleedHeight) return '未生成'
  return `${file.aiBleedWidth} x ${file.aiBleedHeight} px`
})
const printPreviewStyle = computed(() => {
  const pageWidth = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const pageHeight = printHeight.value + (bleed.value + CROP_MARK_MM) * 2
  const trimLeft = ((CROP_MARK_MM + bleed.value) / pageWidth) * 100
  const trimTop = ((CROP_MARK_MM + bleed.value) / pageHeight) * 100
  const trimWidth = (printWidth.value / pageWidth) * 100
  const trimHeight = (printHeight.value / pageHeight) * 100

  return {
    '--page-ratio': `${pageWidth} / ${pageHeight}`,
    '--trim-left': `${trimLeft}%`,
    '--trim-top': `${trimTop}%`,
    '--trim-width': `${trimWidth}%`,
    '--trim-height': `${trimHeight}%`
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

  bleedGenerationError.value = ''
  setDefaultPrintSize()
}

function readFileAsDataUrl(file: Blob): Promise<string> {
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
  bleedGenerationError.value = ''
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

function drawContain(
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
  const drawWidth = sourceRatio >= targetRatio ? width : height * sourceRatio
  const drawHeight = sourceRatio >= targetRatio ? width / sourceRatio : height
  const dx = x + (width - drawWidth) / 2
  const dy = y + (height - drawHeight) / 2

  ctx.drawImage(img, dx, dy, drawWidth, drawHeight)
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

async function createBleedCanvas(source: string, width: number, height: number, bleedSource?: string) {
  const img = await loadImage(source)
  const bleedImg = bleedSource ? await loadImage(bleedSource) : undefined
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
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  if (bleedImg) {
    drawContain(ctx, bleedImg, 0, 0, width, height, bleedImg.naturalWidth, bleedImg.naturalHeight)
    return canvas
  } else {
    drawCover(ctx, img, 0, 0, width, height, img.naturalWidth, img.naturalHeight)
  }
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

async function createPrintSheetDataUrl(source: string, maxSide = 1800, bleedSource?: string) {
  const sheetWidthMm = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetHeightMm = printHeight.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetRatio = sheetWidthMm / sheetHeightMm
  const sheetWidth = sheetRatio >= 1 ? maxSide : Math.max(1, Math.round(maxSide * sheetRatio))
  const sheetHeight = sheetRatio >= 1 ? Math.max(1, Math.round(maxSide / sheetRatio)) : maxSide
  const scale = sheetWidth / sheetWidthMm
  const markPx = Math.max(1, Math.round(CROP_MARK_MM * scale))
  const artworkWidth = Math.max(1, sheetWidth - markPx * 2)
  const artworkHeight = Math.max(1, sheetHeight - markPx * 2)
  const artwork = await createBleedCanvas(source, artworkWidth, artworkHeight, bleedSource)
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

async function createPrintSheetDataUrlAtDpi(source: string, bleedSource?: string) {
  const canvas = await createPrintSheetCanvasAtDpi(source, bleedSource)
  return canvas.toDataURL('image/jpeg', 0.95)
}

async function createPrintSheetCanvasAtDpi(source: string, bleedSource?: string) {
  const sheetWidthMm = printWidth.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetHeightMm = printHeight.value + (bleed.value + CROP_MARK_MM) * 2
  const sheetWidth = Math.ceil((sheetWidthMm / MM_PER_INCH) * printDpi.value)
  const sheetHeight = Math.ceil((sheetHeightMm / MM_PER_INCH) * printDpi.value)
  const scale = sheetWidth / sheetWidthMm
  const markPx = Math.max(1, Math.round(CROP_MARK_MM * scale))
  const artworkWidth = Math.max(1, sheetWidth - markPx * 2)
  const artworkHeight = Math.max(1, sheetHeight - markPx * 2)
  const artwork = await createBleedCanvas(source, artworkWidth, artworkHeight, bleedSource)
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

async function updateBleedPreview(fileOverride?: UploadedFile) {
  const file = fileOverride || selectedFile.value
  if (!file) {
    bleedPreview.value = ''
    bleedPreviewVersion.value += 1
    return
  }

  try {
    if (file.cmykData) {
      bleedPreview.value = file.cmykData
      bleedPreviewVersion.value += 1
      return
    }
    bleedPreview.value = await createPrintSheetDataUrl(file.preview, 1200, file.aiBleedPreview)
  } catch (error) {
    bleedPreview.value = file.aiBleedPreview || file.cmykData || file.preview
  }
  bleedPreviewVersion.value += 1
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
    const printImage = await createPrintSheetDataUrl(file.preview, 2200, file.aiBleedPreview)
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
  if (file.aiBleedFile) {
    formData.append('bleedImage', file.aiBleedFile, file.aiBleedFile.name)
  }
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

function openUpscaleModal() {
  if (!selectedFile.value || isConverting.value) return
  selectedUpscaleResolution.value = '2k'
  upscaleError.value = ''
  upscaleTaskId.value = ''
  upscalePollingStatus.value = ''
  isUpscaleModalOpen.value = true
}

function closeUpscaleModal() {
  if (isGeneratingImage.value) return
  isUpscaleModalOpen.value = false
  upscaleError.value = ''
  upscaleTaskId.value = ''
  upscalePollingStatus.value = ''
}

function sleep(ms: number) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = UPSCALE_STATUS_TIMEOUT_MS) {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs)
  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal
    })
  } finally {
    window.clearTimeout(timeout)
  }
}

async function readJsonResponse(response: Response) {
  if (!response.ok) {
    const message = await response.text().catch(() => '')
    throw new Error(message || '高清生成服务请求失败')
  }
  return response.json()
}

function getTaskId(payload: unknown) {
  if (!payload || typeof payload !== 'object') return ''
  const data = (payload as { data?: unknown }).data
  if (!data || typeof data !== 'object') return ''
  const taskId = (data as { taskId?: unknown }).taskId
  return typeof taskId === 'string' ? taskId : ''
}

function parseResultUrl(payload: unknown) {
  if (!payload || typeof payload !== 'object') return ''
  const data = (payload as { data?: unknown }).data
  if (!data || typeof data !== 'object') return ''
  const resultJson = (data as { resultJson?: unknown }).resultJson
  if (typeof resultJson !== 'string') return ''

  try {
    const parsed = JSON.parse(resultJson)
    const urls = parsed?.resultUrls
    return Array.isArray(urls) && typeof urls[0] === 'string' ? urls[0] : ''
  } catch {
    return ''
  }
}

function getTaskState(payload: unknown) {
  if (!payload || typeof payload !== 'object') return ''
  const data = (payload as { data?: unknown }).data
  if (!data || typeof data !== 'object') return ''
  const state = (data as { state?: unknown }).state
  return typeof state === 'string' ? state : ''
}

function getTaskFailureMessage(payload: unknown) {
  if (!payload || typeof payload !== 'object') return ''
  const message = (payload as { message?: unknown }).message
  const normalizedMessage = typeof message === 'string' && message.toLowerCase() !== 'success' ? message : ''
  const data = (payload as { data?: unknown }).data
  if (!data || typeof data !== 'object') return normalizedMessage
  const failMsg = (data as { failMsg?: unknown }).failMsg
  const failCode = (data as { failCode?: unknown }).failCode
  if (typeof failMsg === 'string' && failMsg) return failMsg
  if (typeof failCode === 'string' && failCode) return failCode
  if (normalizedMessage) return normalizedMessage
  return ''
}

function closestApixoAspectRatio(width: number, height: number) {
  const targetRatio = width / height
  const supportedRatios = [
    { value: '1:1', ratio: 1 },
    { value: '3:4', ratio: 3 / 4 },
    { value: '4:3', ratio: 4 / 3 },
    { value: '9:16', ratio: 9 / 16 },
    { value: '16:9', ratio: 16 / 9 }
  ]

  return supportedRatios.reduce((best, option) => {
    return Math.abs(option.ratio - targetRatio) < Math.abs(best.ratio - targetRatio) ? option : best
  }).value
}

function bleedAspectRatioForApi() {
  return closestApixoAspectRatio(printWidth.value + bleed.value * 2, printHeight.value + bleed.value * 2)
}

async function requestImageTask(imageDataUrl: string, resolution: UpscaleResolution, prompt?: string, aspectRatio = 'auto') {
  const response = await fetch(UPSCALE_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      imageDataUrl,
      resolution,
      prompt,
      aspectRatio
    })
  })
  const payload = await readJsonResponse(response)
  const taskId = getTaskId(payload)
  if (!taskId) throw new Error('高清生成任务创建失败，未返回 taskId。')
  return taskId
}

async function requestUpscaleTask(file: UploadedFile, resolution: UpscaleResolution) {
  return requestImageTask(file.preview, resolution)
}

async function waitForUpscaleResult(taskId: string, onStatus?: (message: string) => void) {
  const startedAt = Date.now()
  let attempt = 0
  let consecutiveErrors = 0

  while (Date.now() - startedAt < UPSCALE_MAX_WAIT_MS) {
    attempt += 1
    onStatus?.(`正在查询生成状态，第 ${attempt} 次...`)

    try {
      const response = await fetchWithTimeout(`${UPSCALE_STATUS_URL}?taskId=${encodeURIComponent(taskId)}`, {
        cache: 'no-store'
      })
      const payload = await readJsonResponse(response)
      const state = getTaskState(payload)
      const failure = getTaskFailureMessage(payload)
      consecutiveErrors = 0

      if (state === 'success') {
        const resultUrl = parseResultUrl(payload)
        if (!resultUrl) throw new Error('高清图片已生成，但未返回图片地址。')
        onStatus?.('生成完成，正在下载图片...')
        return resultUrl
      }
      if (['failed', 'fail', 'error', 'canceled', 'cancelled'].includes(state)) {
        throw new Error(failure ? `高清图片生成失败：${failure}` : '高清图片生成失败，请稍后重试。')
      }
      if (failure && state !== 'processing') {
        throw new Error(`高清图片生成失败：${failure}`)
      }

      onStatus?.(state ? `任务状态：${state}，${UPSCALE_POLL_INTERVAL_MS / 1000} 秒后继续查询。` : `${UPSCALE_POLL_INTERVAL_MS / 1000} 秒后继续查询。`)
    } catch (error) {
      consecutiveErrors += 1
      if (consecutiveErrors >= UPSCALE_MAX_CONSECUTIVE_POLL_ERRORS) {
        throw error
      }
      onStatus?.(`状态查询暂时失败，正在自动重试（${consecutiveErrors}/${UPSCALE_MAX_CONSECUTIVE_POLL_ERRORS}）。`)
    }

    await sleep(UPSCALE_POLL_INTERVAL_MS)
  }

  throw new Error('高清图片生成超时，请稍后查看任务状态或重新生成。')
}

async function fetchGeneratedImage(resultUrl: string) {
  const response = await fetch(`${IMAGE_PROXY_URL}?url=${encodeURIComponent(resultUrl)}`)
  if (!response.ok) {
    const message = await response.text().catch(() => '')
    throw new Error(message || '无法下载生成后的高清图片。')
  }
  const contentType = response.headers.get('Content-Type') || ''
  const fallbackType = resultUrl.match(/\.jpe?g(\?|$)/i)
    ? 'image/jpeg'
    : resultUrl.match(/\.webp(\?|$)/i)
      ? 'image/webp'
      : 'image/png'
  return new Blob([await response.arrayBuffer()], {
    type: contentType.startsWith('image/') ? contentType : fallbackType
  })
}

function extensionFromMime(type: string) {
  if (type === 'image/jpeg') return 'jpg'
  if (type === 'image/webp') return 'webp'
  return 'png'
}

async function replaceUploadedImage(blob: Blob, resolution: UpscaleResolution) {
  const file = selectedFile.value
  if (!file) return

  const mimeType = blob.type || 'image/png'
  const extension = extensionFromMime(mimeType)
  const baseName = file.file.name.replace(/\.[^.]+$/, '')
  const enhancedFile = new File([blob], `${baseName}-${resolution}.${extension}`, {
    type: mimeType,
    lastModified: Date.now()
  })
  const preview = await readFileAsDataUrl(enhancedFile)
  const dimensions = await getImageDimensions(preview)
  const embeddedDpi = await readImageDpi(enhancedFile).catch(() => undefined)

  files.value = [{
    ...file,
    id: generateId(),
    file: enhancedFile,
    preview,
    width: dimensions.width,
    height: dimensions.height,
    dpi: embeddedDpi?.value ? Math.round(embeddedDpi.value) : ASSUMED_SOURCE_DPI,
    dpiSource: embeddedDpi?.source || 'default',
    status: 'pending',
    cmykData: undefined,
    aiBleedPreview: undefined,
    aiBleedFile: undefined,
    aiBleedWidth: undefined,
    aiBleedHeight: undefined
  }]
  generatedPdf.value = null
  generatedPdfProfile.value = null
  await updateBleedPreview()
}

async function generateUpscaledImage() {
  const file = selectedFile.value
  if (!file) return

  isGeneratingImage.value = true
  upscaleError.value = ''
  upscaleTaskId.value = ''
  upscalePollingStatus.value = '正在创建生成任务...'

  try {
    const taskId = await requestUpscaleTask(file, selectedUpscaleResolution.value)
    upscaleTaskId.value = taskId
    upscalePollingStatus.value = '任务已创建，正在启动状态查询...'
    const resultUrl = await waitForUpscaleResult(taskId, message => {
      upscalePollingStatus.value = message
    })
    const imageBlob = await fetchGeneratedImage(resultUrl)
    await replaceUploadedImage(imageBlob, selectedUpscaleResolution.value)
    isUpscaleModalOpen.value = false
  } catch (error) {
    upscaleError.value = error instanceof Error ? error.message : '高清图片生成失败，请稍后重试。'
  }

  if (!upscaleError.value) {
    upscaleTaskId.value = ''
    upscalePollingStatus.value = ''
  }
  isGeneratingImage.value = false
}

function createBleedExpansionPrompt() {
  const pageWidthMm = printWidth.value + bleed.value * 2
  const pageHeightMm = printHeight.value + bleed.value * 2
  const aspectRatio = bleedAspectRatioForApi()

  return [
    'Outpaint the image strictly inside the magenta rectangular frame.',
    'Keep the original center image unchanged.',
    'Fill only the white area between the original image and the magenta frame with natural continuation of the image.',
    `The source artwork size is ${printWidth.value}mm x ${printHeight.value}mm, with ${bleed.value}mm bleed added on all four sides.`,
    `The full framed canvas represents ${pageWidthMm}mm x ${pageHeightMm}mm and must stay close to aspect ratio ${aspectRatio}.`,
    'Do not make the output wider than the input guide image.',
    'Do not change anything outside the magenta frame.',
    'Do not zoom, crop, shrink, stretch, move, or redesign the original image.',
    'Remove the magenta frame in the final result.',
    'The final result must keep the same canvas size as the input.'
  ].join(' ')
}

function upscaleResolutionMaxSide(resolution: UpscaleResolution) {
  return resolution === '4k' ? 4096 : 2048
}

function targetBleedCanvasSize(resolution: UpscaleResolution) {
  const pageWidthMm = printWidth.value + bleed.value * 2
  const pageHeightMm = printHeight.value + bleed.value * 2
  const pageRatio = pageWidthMm / pageHeightMm
  const maxSide = upscaleResolutionMaxSide(resolution)

  return {
    width: pageRatio >= 1 ? maxSide : Math.max(1, Math.round(maxSide * pageRatio)),
    height: pageRatio >= 1 ? Math.max(1, Math.round(maxSide / pageRatio)) : maxSide
  }
}

async function createAiBleedGuideDataUrl(source: string, resolution: UpscaleResolution) {
  const img = await loadImage(source)
  const pageWidthMm = printWidth.value + bleed.value * 2
  const pageHeightMm = printHeight.value + bleed.value * 2
  const canvas = document.createElement('canvas')
  const size = targetBleedCanvasSize(resolution)
  canvas.width = size.width
  canvas.height = size.height

  const ctx = canvas.getContext('2d')!
  const bleedX = Math.max(1, Math.round((bleed.value / pageWidthMm) * canvas.width))
  const bleedY = Math.max(1, Math.round((bleed.value / pageHeightMm) * canvas.height))
  const trimX = bleedX
  const trimY = bleedY
  const trimWidth = Math.max(1, canvas.width - bleedX * 2)
  const trimHeight = Math.max(1, canvas.height - bleedY * 2)

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  drawCover(ctx, img, trimX, trimY, trimWidth, trimHeight, img.naturalWidth, img.naturalHeight)
  ctx.save()
  ctx.strokeStyle = '#ff00ff'
  ctx.lineWidth = Math.max(2, Math.round(Math.min(canvas.width, canvas.height) * 0.002))
  ctx.strokeRect(
    ctx.lineWidth / 2,
    ctx.lineWidth / 2,
    canvas.width - ctx.lineWidth,
    canvas.height - ctx.lineWidth
  )
  ctx.restore()

  return canvas.toDataURL('image/jpeg', 0.9)
}

function initializeAiCrop() {
  const img = cropImageRef.value
  if (!img?.naturalWidth || !img.naturalHeight) return

  const targetRatio = (printWidth.value + bleed.value * 2) / (printHeight.value + bleed.value * 2)
  const imageRatio = img.naturalWidth / img.naturalHeight
  let width = 100
  let height = 100

  if (imageRatio > targetRatio) {
    width = (targetRatio / imageRatio) * 100
  } else {
    height = (imageRatio / targetRatio) * 100
  }

  cropRect.value = {
    x: (100 - width) / 2,
    y: (100 - height) / 2,
    width,
    height
  }
}

function startCropDrag(event: PointerEvent) {
  const img = cropImageRef.value
  if (!img) return
  event.preventDefault()
  ;(event.currentTarget as HTMLElement).setPointerCapture(event.pointerId)
  cropDragStart.value = {
    pointerId: event.pointerId,
    mode: 'move',
    startX: event.clientX,
    startY: event.clientY,
    rect: { ...cropRect.value }
  }
}

function startCropResize(edge: CropResizeEdge, event: PointerEvent) {
  const img = cropImageRef.value
  const box = (event.currentTarget as HTMLElement).closest('.crop-box') as HTMLElement | null
  if (!img || !box) return
  event.preventDefault()
  event.stopPropagation()
  box.setPointerCapture(event.pointerId)
  cropDragStart.value = {
    pointerId: event.pointerId,
    mode: 'resize',
    edge,
    startX: event.clientX,
    startY: event.clientY,
    rect: { ...cropRect.value }
  }
}

function moveCropDrag(event: PointerEvent) {
  const drag = cropDragStart.value
  const img = cropImageRef.value
  if (!drag || drag.pointerId !== event.pointerId || !img) return

  const bounds = img.getBoundingClientRect()
  const dx = ((event.clientX - drag.startX) / bounds.width) * 100
  const dy = ((event.clientY - drag.startY) / bounds.height) * 100
  const minSize = 8

  if (drag.mode === 'resize' && drag.edge) {
    let left = drag.rect.x
    let top = drag.rect.y
    let right = drag.rect.x + drag.rect.width
    let bottom = drag.rect.y + drag.rect.height

    if (drag.edge.includes('w')) {
      left = clamp(drag.rect.x + dx, 0, right - minSize)
    }
    if (drag.edge.includes('e')) {
      right = clamp(drag.rect.x + drag.rect.width + dx, left + minSize, 100)
    }
    if (drag.edge.includes('n')) {
      top = clamp(drag.rect.y + dy, 0, bottom - minSize)
    }
    if (drag.edge.includes('s')) {
      bottom = clamp(drag.rect.y + drag.rect.height + dy, top + minSize, 100)
    }

    cropRect.value = {
      x: left,
      y: top,
      width: right - left,
      height: bottom - top
    }
    return
  }

  cropRect.value = {
    ...drag.rect,
    x: clamp(drag.rect.x + dx, 0, 100 - drag.rect.width),
    y: clamp(drag.rect.y + dy, 0, 100 - drag.rect.height)
  }
}

function endCropDrag(event: PointerEvent) {
  if (cropDragStart.value?.pointerId === event.pointerId) {
    cropDragStart.value = null
  }
}

async function cropAiBleedPreviewToBlob(source: string, resolution: UpscaleResolution) {
  const img = await loadImage(source)
  const size = targetBleedCanvasSize(resolution)
  const selectedCanvas = document.createElement('canvas')
  selectedCanvas.width = Math.max(1, Math.round((cropRect.value.width / 100) * img.naturalWidth))
  selectedCanvas.height = Math.max(1, Math.round((cropRect.value.height / 100) * img.naturalHeight))
  const selectedCtx = selectedCanvas.getContext('2d')!
  const sourceX = Math.round((cropRect.value.x / 100) * img.naturalWidth)
  const sourceY = Math.round((cropRect.value.y / 100) * img.naturalHeight)

  selectedCtx.imageSmoothingEnabled = true
  selectedCtx.imageSmoothingQuality = 'high'
  selectedCtx.drawImage(
    img,
    sourceX,
    sourceY,
    selectedCanvas.width,
    selectedCanvas.height,
    0,
    0,
    selectedCanvas.width,
    selectedCanvas.height
  )

  const canvas = document.createElement('canvas')
  canvas.width = size.width
  canvas.height = size.height
  const ctx = canvas.getContext('2d')!

  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  ctx.imageSmoothingEnabled = true
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(selectedCanvas, 0, 0, canvas.width, canvas.height)

  return new Promise<Blob>((resolve, reject) => {
    canvas.toBlob(result => {
      if (result) {
        resolve(result)
      } else {
        reject(new Error('无法整理 AI 扩图结果'))
      }
    }, 'image/png', 0.98)
  })
}

async function applyAiBleedBlob(imageBlob: Blob) {
  const file = selectedFile.value
  if (!file) return

  const mimeType = imageBlob.type || 'image/png'
  const extension = extensionFromMime(mimeType)
  const baseName = file.file.name.replace(/\.[^.]+$/, '')
  const aiBleedFile = new File([imageBlob], `${baseName}-ai-bleed-${selectedBleedResolution.value}.${extension}`, {
    type: mimeType,
    lastModified: Date.now()
  })
  const aiBleedPreview = await readFileAsDataUrl(aiBleedFile)
  const aiBleedDimensions = await getImageDimensions(aiBleedPreview)
  const updatedFile: UploadedFile = {
    ...file,
    aiBleedFile,
    aiBleedPreview,
    aiBleedWidth: aiBleedDimensions.width,
    aiBleedHeight: aiBleedDimensions.height,
    cmykData: undefined,
    status: file.status === 'done' ? 'pending' : file.status
  }

  files.value = [updatedFile]
  generatedPdf.value = null
  generatedPdfProfile.value = null
  await nextTick()
  await updateBleedPreview(updatedFile)
}

async function confirmAiCrop() {
  if (!pendingAiCropPreview.value) return

  isApplyingAiCrop.value = true
  try {
    const croppedBlob = await cropAiBleedPreviewToBlob(pendingAiCropPreview.value, selectedBleedResolution.value)
    await applyAiBleedBlob(croppedBlob)
    isAiCropModalOpen.value = false
    pendingAiCropPreview.value = ''
  } catch (error) {
    bleedGenerationError.value = error instanceof Error ? error.message : 'AI 扩图裁剪失败，请重试。'
  }
  isApplyingAiCrop.value = false
}

function cancelAiCrop() {
  if (isApplyingAiCrop.value) return
  isAiCropModalOpen.value = false
  pendingAiCropPreview.value = ''
}

async function generateAiBleedImage() {
  const file = selectedFile.value
  if (!file) return

  isGeneratingBleed.value = true
  bleedGenerationError.value = ''
  pendingAiCropPreview.value = ''
  bleedTaskId.value = ''
  bleedPollingStatus.value = '正在创建 AI 扩图任务...'

  try {
    const guideImage = await createAiBleedGuideDataUrl(file.preview, selectedBleedResolution.value)
    const taskId = await requestImageTask(
      guideImage,
      selectedBleedResolution.value,
      createBleedExpansionPrompt(),
      bleedAspectRatioForApi()
    )
    bleedTaskId.value = taskId
    bleedPollingStatus.value = '任务已创建，正在启动状态查询...'
    const resultUrl = await waitForUpscaleResult(taskId, message => {
      bleedPollingStatus.value = message
    })
    const rawImageBlob = await fetchGeneratedImage(resultUrl)
    pendingAiCropPreview.value = await readFileAsDataUrl(rawImageBlob)
    await nextTick()
    isAiCropModalOpen.value = true
    await nextTick()
    initializeAiCrop()
  } catch (error) {
    bleedGenerationError.value = error instanceof Error ? error.message : 'AI 智能扩图失败，请稍后重试。'
  }

  isGeneratingBleed.value = false
  if (!bleedGenerationError.value) {
    bleedTaskId.value = ''
    bleedPollingStatus.value = ''
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
          <div class="w-full overflow-hidden rounded-xl bg-secondary md:w-56">
            <div class="aspect-[4/3]">
              <img
                :src="selectedFile.cmykData || selectedFile.preview"
                :alt="selectedFile.file.name"
                class="h-full w-full object-contain"
              />
            </div>
            <div class="border-t border-border/60 bg-background/80 px-3 py-2 text-center text-xs text-muted-foreground">
              图片分辨率：{{ selectedFile.width }} x {{ selectedFile.height }} px
            </div>
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
                  {{ selectedFile.aiBleedPreview ? `已使用 AI 智能扩图补全 ${bleed}mm 出血，裁切参考线完全位于出血图片外侧。` : `生成 AI 智能扩图后，会用扩展后的边缘补全 ${bleed}mm 出血。` }}
                </p>
              </div>
            </div>

            <div class="mt-4 rounded-xl border border-border bg-background p-4">
              <div class="flex flex-wrap items-center justify-between gap-3">
                <div class="min-w-0 flex-1">
                  <p class="text-sm font-medium text-foreground">AI 智能扩图</p>
                  <p class="mt-1 text-xs text-muted-foreground">
                    {{ selectedFile.aiBleedPreview ? '当前预览和导出会使用 AI 扩图补边。' : '为出血区域生成自然延展的图片边缘。' }}
                  </p>
                </div>
                <div class="flex shrink-0 items-center gap-2">
                  <select
                    v-model="selectedBleedResolution"
                    :disabled="isGeneratingBleed"
                    class="h-10 w-20 rounded-lg border border-border bg-background px-3 text-sm text-foreground outline-none focus:border-primary"
                  >
                    <option
                      v-for="option in UPSCALE_OPTIONS"
                      :key="option.key"
                      :value="option.key"
                    >
                      {{ option.label }}
                    </option>
                  </select>
                  <button
                    type="button"
                    class="btn-primary flex h-10 items-center gap-2 whitespace-nowrap rounded-lg bg-accent px-4 text-sm font-medium text-accent-foreground disabled:cursor-not-allowed disabled:opacity-50"
                    :disabled="isGeneratingBleed || isGeneratingImage || isConverting"
                    @click="generateAiBleedImage"
                  >
                    <Loader2 v-if="isGeneratingBleed" class="h-4 w-4 animate-spin" />
                    <Sparkles v-else class="h-4 w-4" />
                    {{ isGeneratingBleed ? '扩图中...' : selectedFile.aiBleedPreview ? '重新扩图' : '生成' }}
                  </button>
                </div>
              </div>

              <div class="mt-4 grid gap-3 text-xs text-muted-foreground sm:grid-cols-3">
                <div class="rounded-lg bg-secondary px-3 py-2">
                  <span class="block font-medium text-foreground">成品区域像素</span>
                  <span class="mt-1 block">{{ requiredPixels.width }} x {{ requiredPixels.height }} px</span>
                </div>
                <div class="rounded-lg bg-secondary px-3 py-2">
                  <span class="block font-medium text-foreground">出血画布像素</span>
                  <span class="mt-1 block">{{ bleedArtworkPixels.width }} x {{ bleedArtworkPixels.height }} px</span>
                </div>
                <div class="rounded-lg bg-secondary px-3 py-2">
                  <span class="block font-medium text-foreground">AI 扩图像素</span>
                  <span class="mt-1 block">{{ aiBleedPixelsLabel }}</span>
                </div>
              </div>

              <div
                v-if="isGeneratingBleed || bleedTaskId || bleedPollingStatus"
                class="mt-3 rounded-lg bg-secondary px-3 py-2 text-xs text-muted-foreground"
              >
                <span v-if="bleedTaskId" class="block">任务 ID：{{ bleedTaskId }}</span>
                <span class="block">{{ bleedPollingStatus || '正在准备状态查询...' }}</span>
              </div>

              <div
                v-if="bleedGenerationError"
                class="mt-3 rounded-lg border border-accent/30 bg-accent/10 p-3 text-sm text-foreground"
              >
                <div class="flex gap-2">
                  <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" />
                  <p>{{ bleedGenerationError }}</p>
                </div>
              </div>
            </div>

            <div class="mt-5 rounded-2xl bg-secondary p-5">
              <div
                class="print-preview relative mx-auto w-full max-w-sm overflow-hidden bg-white shadow-lg"
                :style="printPreviewStyle"
              >
                <img
                  :key="`print-preview-${selectedFile.id}-${bleedPreviewVersion}`"
                  :src="printPreviewImageSrc"
                  :alt="selectedFile.file.name"
                  class="absolute inset-0 h-full w-full object-contain"
                />
                <div
                  class="trim-guide pointer-events-none absolute"
                  aria-hidden="true"
                >
                  <span class="absolute left-2 top-2 rounded bg-background/85 px-2 py-1 text-[10px] font-medium text-foreground shadow-sm">
                    成品区
                  </span>
                </div>
                <div
                  v-if="isGeneratingBleed"
                  class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-background/85 px-4 text-center backdrop-blur-sm"
                >
                  <Loader2 class="h-8 w-8 animate-spin text-accent" />
                  <div>
                    <p class="text-sm font-medium text-foreground">AI 智能扩图中</p>
                    <p class="mt-1 text-xs text-muted-foreground">{{ bleedPollingStatus || '完成后会打开裁剪确认弹窗' }}</p>
                    <p v-if="bleedTaskId" class="mt-1 text-[10px] text-muted-foreground">任务 ID：{{ bleedTaskId }}</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="hasFiles" class="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
        <button
          @click="openUpscaleModal"
          :disabled="isGeneratingImage || isConverting"
          class="btn-primary bg-accent text-accent-foreground px-8 py-4 rounded-xl text-base font-medium flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed w-full sm:w-auto justify-center"
        >
          <template v-if="isGeneratingImage">
            <Loader2 class="w-5 h-5 animate-spin" />
            生成中...
          </template>
          <template v-else>
            <Sparkles class="w-5 h-5" />
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

      <div
        v-if="isAiCropModalOpen && pendingAiCropPreview"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4 py-6"
        @click="cancelAiCrop"
      >
        <div
          class="relative flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-card shadow-2xl"
          @click.stop
        >
          <div
            v-if="isApplyingAiCrop"
            class="absolute inset-0 z-30 flex flex-col items-center justify-center gap-4 bg-background/85 px-6 text-center backdrop-blur-sm"
          >
            <Loader2 class="h-10 w-10 animate-spin text-accent" />
            <div>
              <p class="text-lg font-medium text-foreground">正在应用裁剪区域</p>
              <p class="mt-1 text-sm text-muted-foreground">预览和导出文件会使用确认后的扩图结果。</p>
            </div>
          </div>

          <div class="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h3 class="text-xl font-serif font-medium text-foreground">确认 AI 扩图区域</h3>
              <p class="mt-1 text-sm text-muted-foreground">拖动选框调整位置，拉动边角自由调整大小，确认后会铺满印刷画布。</p>
            </div>
            <button
              class="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              :disabled="isApplyingAiCrop"
              aria-label="关闭"
              @click="cancelAiCrop"
            >
              <X class="h-4 w-4" />
            </button>
          </div>

          <div class="min-h-0 flex-1 overflow-auto bg-secondary p-5">
            <div class="crop-stage mx-auto">
              <img
                ref="cropImageRef"
                :src="pendingAiCropPreview"
                alt="AI 扩图结果"
                class="block max-h-[62vh] max-w-full select-none"
                draggable="false"
                @load="initializeAiCrop"
              />
              <div
                class="crop-box"
                :style="{
                  left: `${cropRect.x}%`,
                  top: `${cropRect.y}%`,
                  width: `${cropRect.width}%`,
                  height: `${cropRect.height}%`
                }"
                @pointerdown="startCropDrag"
                @pointermove="moveCropDrag"
                @pointerup="endCropDrag"
                @pointercancel="endCropDrag"
              >
                <span class="crop-box-label">印刷预览区域</span>
                <span class="crop-handle crop-handle-nw" @pointerdown.stop="startCropResize('nw', $event)" />
                <span class="crop-handle crop-handle-n" @pointerdown.stop="startCropResize('n', $event)" />
                <span class="crop-handle crop-handle-ne" @pointerdown.stop="startCropResize('ne', $event)" />
                <span class="crop-handle crop-handle-e" @pointerdown.stop="startCropResize('e', $event)" />
                <span class="crop-handle crop-handle-se" @pointerdown.stop="startCropResize('se', $event)" />
                <span class="crop-handle crop-handle-s" @pointerdown.stop="startCropResize('s', $event)" />
                <span class="crop-handle crop-handle-sw" @pointerdown.stop="startCropResize('sw', $event)" />
                <span class="crop-handle crop-handle-w" @pointerdown.stop="startCropResize('w', $event)" />
              </div>
            </div>
          </div>

          <div class="flex flex-col-reverse gap-3 border-t border-border px-5 py-4 sm:flex-row sm:justify-end">
            <button
              type="button"
              class="rounded-xl border border-border bg-background px-5 py-3 text-sm font-medium text-muted-foreground transition-colors hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="isApplyingAiCrop"
              @click="cancelAiCrop"
            >
              取消
            </button>
            <button
              type="button"
              class="btn-primary flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="isApplyingAiCrop"
              @click="confirmAiCrop"
            >
              <Loader2 v-if="isApplyingAiCrop" class="h-4 w-4 animate-spin" />
              <CheckCircle v-else class="h-4 w-4" />
              确认使用
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="isUpscaleModalOpen && selectedFile"
        class="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4 py-6"
        @click="closeUpscaleModal"
      >
        <div
          class="relative w-full max-w-4xl overflow-hidden rounded-2xl bg-card shadow-2xl"
          @click.stop
        >
          <div
            v-if="isGeneratingImage"
            class="absolute inset-0 z-20 flex flex-col items-center justify-center gap-4 bg-background/85 px-6 text-center backdrop-blur-sm"
          >
            <Loader2 class="h-10 w-10 animate-spin text-accent" />
            <div>
              <p class="text-lg font-medium text-foreground">高清图片生成中</p>
              <p class="mt-1 text-sm text-muted-foreground">
                {{ upscaleTaskId ? `任务 ID：${upscaleTaskId}` : '正在创建生成任务...' }}
              </p>
              <p class="mt-1 text-xs text-muted-foreground">
                {{ upscalePollingStatus || '正在准备状态查询...' }}
              </p>
            </div>
          </div>

          <div class="flex items-center justify-between border-b border-border px-5 py-4">
            <div>
              <h3 class="text-xl font-serif font-medium text-foreground">生成高清印刷图片</h3>
              <p class="mt-1 text-sm text-muted-foreground">选择目标分辨率，生成完成后会替换当前上传图片。</p>
            </div>
            <button
              class="flex h-9 w-9 items-center justify-center rounded-lg bg-secondary text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              :disabled="isGeneratingImage"
              aria-label="关闭"
              @click="closeUpscaleModal"
            >
              <X class="h-4 w-4" />
            </button>
          </div>

          <div class="grid gap-0 md:grid-cols-[minmax(0,1fr)_360px]">
            <div class="bg-secondary p-5">
              <div class="aspect-[4/3] h-full min-h-[280px] overflow-hidden rounded-xl bg-background">
                <img
                  :src="selectedFile.preview"
                  :alt="selectedFile.file.name"
                  class="h-full w-full object-contain"
                />
              </div>
            </div>

            <div class="p-5">
              <p class="text-sm font-medium text-foreground">目标分辨率</p>
              <div class="mt-3 grid grid-cols-2 gap-3">
                <button
                  v-for="option in UPSCALE_OPTIONS"
                  :key="option.key"
                  type="button"
                  class="rounded-xl border px-4 py-3 text-left transition-colors"
                  :class="selectedUpscaleResolution === option.key ? 'border-accent bg-accent/10 text-foreground' : 'border-border bg-background text-muted-foreground hover:bg-secondary'"
                  :disabled="isGeneratingImage"
                  @click="selectedUpscaleResolution = option.key"
                >
                  <span class="block text-base font-semibold">{{ option.label }}</span>
                  <span class="mt-1 block text-xs">{{ option.pixels }}</span>
                </button>
              </div>

              <div class="mt-5 rounded-xl bg-secondary p-4 text-sm text-muted-foreground">
                当前图片：{{ selectedFile.width }} x {{ selectedFile.height }} px
                <span class="mt-1 block">生成后会刷新图片尺寸、预览和印刷清晰度提示。</span>
              </div>

              <div
                v-if="upscaleError"
                class="mt-4 rounded-xl border border-accent/30 bg-accent/10 p-4 text-sm text-foreground"
              >
                <div class="flex gap-2">
                  <AlertTriangle class="mt-0.5 h-4 w-4 flex-shrink-0 text-accent" />
                  <p>{{ upscaleError }}</p>
                </div>
              </div>

              <button
                type="button"
                class="btn-primary mt-6 flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-base font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="isGeneratingImage"
                @click="generateUpscaledImage"
              >
                <Loader2 v-if="isGeneratingImage" class="h-5 w-5 animate-spin" />
                <Sparkles v-else class="h-5 w-5" />
                {{ isGeneratingImage ? '生成中...' : '生成' }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.print-preview {
  aspect-ratio: var(--page-ratio);
}

.trim-guide {
  left: var(--trim-left);
  top: var(--trim-top);
  width: var(--trim-width);
  height: var(--trim-height);
  border: 1px dashed rgba(212, 121, 90, 0.95);
  box-shadow: 0 0 0 999px rgba(255, 255, 255, 0.08);
}

.crop-stage {
  position: relative;
  display: block;
  width: fit-content;
  max-width: 100%;
  margin-inline: auto;
  touch-action: none;
}

.crop-box {
  position: absolute;
  cursor: move;
  border: 2px solid hsl(var(--accent));
  background:
    linear-gradient(to right, rgba(255, 255, 255, 0.85) 1px, transparent 1px) 33.333% 0 / 33.333% 100%,
    linear-gradient(to bottom, rgba(255, 255, 255, 0.85) 1px, transparent 1px) 0 33.333% / 100% 33.333%,
    rgba(212, 121, 90, 0.08);
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42);
  user-select: none;
}

.crop-box-label {
  position: absolute;
  left: 0.5rem;
  top: 0.5rem;
  border-radius: 0.5rem;
  background: hsl(var(--background) / 0.9);
  padding: 0.25rem 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: hsl(var(--foreground));
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.12);
}

.crop-handle {
  position: absolute;
  z-index: 2;
  width: 0.9rem;
  height: 0.9rem;
  border: 2px solid hsl(var(--background));
  border-radius: 999px;
  background: hsl(var(--accent));
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.24);
}

.crop-handle-nw {
  left: 0;
  top: 0;
  cursor: nwse-resize;
  transform: translate(-50%, -50%);
}

.crop-handle-n {
  left: 50%;
  top: 0;
  cursor: ns-resize;
  transform: translate(-50%, -50%);
}

.crop-handle-ne {
  right: 0;
  top: 0;
  cursor: nesw-resize;
  transform: translate(50%, -50%);
}

.crop-handle-e {
  right: 0;
  top: 50%;
  cursor: ew-resize;
  transform: translate(50%, -50%);
}

.crop-handle-se {
  right: 0;
  bottom: 0;
  cursor: nwse-resize;
  transform: translate(50%, 50%);
}

.crop-handle-s {
  left: 50%;
  bottom: 0;
  cursor: ns-resize;
  transform: translate(-50%, 50%);
}

.crop-handle-sw {
  left: 0;
  bottom: 0;
  cursor: nesw-resize;
  transform: translate(-50%, 50%);
}

.crop-handle-w {
  left: 0;
  top: 50%;
  cursor: ew-resize;
  transform: translate(-50%, -50%);
}
</style>
