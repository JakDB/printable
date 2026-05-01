# 项目知识速记

## 项目定位

这是一个名为 `rgb-to-cmyk-converter` 的前端工具，用于把 RGB 图片整理成适合印刷交付的 CMYK PDF。当前产品品牌名是 `Printable`，主要流程是上传 PNG/JPG，设置成品尺寸、DPI、出血和印刷 ICC 配置，然后生成带出血与裁切参考线的印刷文件。

## 当前有效技术栈

- 前端：Vue 3 + Vite + TypeScript。
- 样式：Tailwind CSS，主样式入口是 `src/styles/main.css`，设计 token 在 `tailwind.config.js`。
- 图标：`lucide-vue-next`。
- PDF/色彩转换：前端负责生成印刷版面 JPEG；本地 Python 服务使用 Pillow `ImageCms` 做 ICC 转换并输出嵌入 CMYK ICC 的 PDF。
- 包管理文件：仓库有 `pnpm-lock.yaml`，但 `package.json` 脚本可直接用 `npm.cmd` 调用。

## 重要目录和文件

- `src/main.ts`：Vue 应用入口，挂载 `src/App.vue`。
- `src/App.vue`：页面组合，依次渲染 `Header`、`Hero`、`Converter`、`Features`、`Footer`。
- `src/components/Converter.vue`：核心业务组件，包含文件上传、DPI 读取、出血画布、裁切线绘制、预览、下载图片和请求 CMYK PDF 服务的逻辑。
- `server/icc_convert_server.py`：本地 ICC 转换 HTTP 服务，提供 `GET /health` 和 `POST /api/convert-cmyk-pdf`。
- `server/start_icc_server.cjs`：Node 启动器，会寻找能导入 `PIL.ImageCms` 的 Python。
- `public/icc/`：ICC 配置文件来源目录，目前包含 `PSOcoated_v3.icc` 和 `JapanColor2011Coated.icc`。
- `scripts/test_icc_conversion.py`：手工测试脚本，会请求本地转换服务并生成对比图/PDF；其中 `SOURCE` 是硬编码到本机绝对路径，迁移或复用前需要改掉。
- `dist/`、`output/`、`tmp/`、`*.log`：构建产物、测试输出或运行日志，不应作为主要源码编辑。

## 运行和构建

- 前端开发服务：`npm.cmd run dev`
- ICC 转换服务：`npm.cmd run convert-server`
- 生产构建：`npm.cmd run build`
- 预览构建：`npm.cmd run preview`

在 PowerShell 中直接运行 `npm run ...` 可能会被执行策略拦截；当前环境验证过 `npm.cmd run build` 可成功构建。Vite 构建不等同于完整类型检查，项目目前没有单独的 `typecheck` 脚本。

PDF 转换功能需要前端和 ICC 转换服务同时运行。前端固定请求：

```text
http://127.0.0.1:8787/api/convert-cmyk-pdf
```

可以用下面的健康检查确认转换服务在线：

```text
http://127.0.0.1:8787/health
```

## 核心转换流程

1. 用户上传 PNG/JPG，`Converter.vue` 读取 Data URL、图片尺寸和嵌入 DPI。
2. 如果图片没有 DPI 元数据，前端按 `72 DPI` 估算来源 DPI；印刷输出默认使用 `300 DPI`。
3. 用户设置成品宽高、DPI、出血和 ICC 配置。默认出血是 `3mm`，裁切参考线长度也是 `3mm`。
4. 前端用 Canvas 生成印刷版面：原图 cover 到成品区，边缘镜像补出血，再在出血外绘制裁切线。
5. 生成 PDF 时，前端把印刷版面导出为 JPEG，POST 到本地 Python 服务。
6. Python 服务按所选 ICC profile 做 RGB 到 CMYK 的 `ImageCms.profileToProfile` 转换，并手写 PDF 对象，把 CMYK 图像和 OutputIntent/ICC profile 写进 PDF。

## ICC 配置

前端 profile key 和后端 profile key 必须同步：

- `fogra51`：`public/icc/pso-coated_v3/PSOcoated_v3.icc`
- `japan2011`：`public/icc/JapanColor2011Coated/JapanColor2011Coated.icc`

如果新增配置，需要同时更新：

- `src/components/Converter.vue` 里的 `PrintProfileKey`、`PRINT_PROFILES`
- `server/icc_convert_server.py` 里的 `PROFILES`
- 对应的 `public/icc/...` 资源

## 当前代码状态和维护提醒

- 当前仓库不是 Git 仓库；改动前不要假设可以用 Git 历史恢复。
- 主应用源码在 `src/`。根目录下的 `app/`、`components/ui/`、`hooks/`、`lib/`、`styles/` 看起来是未接入当前 Vite/Vue 应用的旧 Next/shadcn 资产；除非明确要迁移，否则优先不要在这些目录里改业务。
- 多个中文文案在现有源码中呈现为 mojibake 乱码，例如页面标题、按钮和说明文字。新增或修正文案时应使用 UTF-8，并最好一次性核对浏览器渲染效果。
- `Converter.vue` 内存在一些前端侧 CMYK/PDF 生成辅助函数，但当前 PDF 生成主路径实际依赖 `createCmykPdfBlob()` 请求本地 Python 服务。
- `server/icc_convert_server.py` 当前允许 CORS `*`，请求体上限为 `250MB`；若部署到共享环境，需要重新评估安全和资源限制。
- `scripts/test_icc_conversion.py` 依赖本地转换服务在线，并会写入 `output/pdf/` 和 `tmp/pdfs/`。
