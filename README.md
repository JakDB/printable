# Printable

Printable 是一个用于印刷交付的 RGB 到 CMYK 转换工具。它可以把 PNG/JPG 图片整理成带出血和裁切参考线的印刷版面，并通过本地 ICC 转换服务生成嵌入 CMYK 色彩配置的 PDF。

## 主要功能

- 上传 PNG/JPG 图片并读取图片尺寸和 DPI 元数据。
- 设置成品宽高、DPI、出血尺寸和印刷 ICC 配置。
- 支持通过 AI 智能扩图生成出血区域，避免裁切后边缘露白。
- 在出血区域外绘制裁切参考线。
- 支持生成 2K/4K 高清印刷图片。
- 支持生成 CMYK PDF，当前内置：
  - FOGRA51 / PSO Coated v3
  - Japan Color 2011 Coated

## 技术栈

- Vue 3
- Vite
- TypeScript
- Tailwind CSS
- lucide-vue-next
- Python + Pillow ImageCms

前端负责上传、预览、排版、出血和裁切线生成；本地 Python 服务负责真正的 ICC 色彩转换和 CMYK PDF 生成。

## 环境要求

- Node.js
- npm 或 pnpm
- Python
- Pillow，并且 Python 环境需要能导入 `PIL.ImageCms`

可以用下面命令检查 Python 环境是否可用：

```bash
python -c "from PIL import ImageCms"
```

如果失败，请先安装 Pillow：

```bash
pip install pillow
```

## 安装依赖

```bash
npm install
```

如果使用 pnpm：

```bash
pnpm install
```

## 本地开发

复制环境变量示例文件，并填写 APIXO 与 MinIO/S3 的真实配置：

```bash
cp .env.example .env.local
```

`npm.cmd run convert-server` 会自动读取 `.env.local` 和 `.env`。真实密钥不要提交到 Git 仓库。

AI 图片增强和 AI 智能扩图需要这些环境变量：

```text
APIXO_API_KEY
MINIO_ENDPOINT
MINIO_PUBLIC_URL
MINIO_ACCESS_KEY
MINIO_SECRET_KEY
MINIO_BUCKET
MINIO_REGION
MINIO_TEMP_IMAGE_TTL_SECONDS
S3_FORCE_PATH_STYLE
```

启动前端开发服务：

```bash
npm.cmd run dev
```

启动本地 ICC 转换服务：

```bash
npm.cmd run convert-server
```

PDF 转换功能需要前端和 ICC 转换服务同时运行。转换服务默认地址是：

```text
http://127.0.0.1:8787
```

健康检查地址：

```text
http://127.0.0.1:8787/health
```

在 Windows PowerShell 中，直接运行 `npm run ...` 可能会被执行策略拦截；如果遇到该问题，请使用 `npm.cmd run ...`。

## 构建

```bash
npm.cmd run build
```

构建产物会输出到 `dist/`。

本地预览构建产物：

```bash
npm.cmd run preview
```

## 项目结构

```text
src/
  main.ts                  Vue 入口
  App.vue                  页面组合
  components/
    Converter.vue          核心转换工具
    Header.vue             顶部导航
    Hero.vue               首屏介绍
    Features.vue           功能介绍
    Footer.vue             页脚
  styles/
    main.css               Tailwind 和全局样式

server/
  icc_convert_server.py    本地 ICC 转换服务
  start_icc_server.cjs     Python 服务启动器

public/
  icc/                     ICC 色彩配置文件

scripts/
  test_icc_conversion.py   手工转换测试脚本
```

## ICC 配置

当前内置配置文件位于 `public/icc/`：

- `public/icc/pso-coated_v3/PSOcoated_v3.icc`
- `public/icc/JapanColor2011Coated/JapanColor2011Coated.icc`

如果要新增印刷配置，需要同时更新：

- `src/components/Converter.vue` 中的 `PrintProfileKey` 和 `PRINT_PROFILES`
- `server/icc_convert_server.py` 中的 `PROFILES`
- `public/icc/` 中对应的 ICC 文件

## 注意事项

- 该项目的 PDF 转换依赖本地服务，不是纯前端离线生成。
- 上传图片会在浏览器中处理，生成 PDF 时会把前端生成的印刷版面 JPEG 发送到本地 `127.0.0.1:8787` 服务。
- `dist/`、`output/`、`tmp/` 和日志文件是本地生成内容，不应提交到仓库。
- `scripts/test_icc_conversion.py` 中的测试图片路径可能需要按本机环境调整。
