<script setup lang="ts">
import { Zap, Printer, Shield, Layers } from 'lucide-vue-next'

const features = [
  {
    icon: Zap,
    title: '快速转换',
    description: '先进的算法确保快速处理，批量图片也能秒速完成转换'
  },
  {
    icon: Printer,
    title: '印刷就绪',
    description: '输出符合印刷行业标准的 CMYK PDF 文件，直接交付印刷厂'
  },
  {
    icon: Shield,
    title: '隐私安全',
    description: '所有处理在本地浏览器完成，图片不会上传到服务器'
  },
  {
    icon: Layers,
    title: '批量处理',
    description: '支持同时上传多张图片，一键转换生成多页 PDF 文档'
  }
]
</script>

<template>
  <section id="features" class="py-20 md:py-32 px-6 md:px-12">
    <div class="max-w-6xl mx-auto">
      <div class="text-center mb-16">
        <h2 class="text-3xl md:text-4xl font-serif font-medium text-foreground">
          为什么选择 Printable
        </h2>
        <p class="mt-4 text-lg text-muted-foreground max-w-2xl mx-auto">
          专为设计师和印刷从业者打造的色彩转换工具
        </p>
      </div>
      
      <div class="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div
          v-for="(feature, index) in features"
          :key="index"
          class="bg-card border border-border rounded-2xl p-6 hover:shadow-lg transition-shadow"
        >
          <div class="w-12 h-12 bg-secondary rounded-xl flex items-center justify-center mb-4">
            <component :is="feature.icon" class="w-6 h-6 text-foreground" />
          </div>
          <h3 class="text-lg font-medium text-foreground mb-2">
            {{ feature.title }}
          </h3>
          <p class="text-sm text-muted-foreground leading-relaxed">
            {{ feature.description }}
          </p>
        </div>
      </div>
      
      <!-- Color Mode Comparison -->
      <div class="mt-20 bg-card border border-border rounded-2xl p-8 md:p-12">
        <div class="grid md:grid-cols-2 gap-12 items-center">
          <div>
            <h3 class="text-2xl md:text-3xl font-serif font-medium text-foreground mb-4">
              RGB vs CMYK
            </h3>
            <p class="text-muted-foreground leading-relaxed mb-6">
              RGB 是屏幕显示使用的加色模式，而 CMYK 是印刷使用的减色模式。
              直接使用 RGB 图片印刷会导致颜色偏差，尤其是鲜艳的蓝色和绿色。
            </p>
            <p class="text-muted-foreground leading-relaxed">
              我们的转换工具会智能调整色彩，最大程度保持原图的视觉效果，
              同时确保印刷输出的准确性。
            </p>
          </div>
          
          <div class="flex flex-col gap-4">
            <div class="bg-secondary rounded-xl p-6">
              <div class="flex items-center gap-4 mb-4">
                <div class="flex gap-2">
                  <div class="w-8 h-8 rounded-lg bg-red-500"></div>
                  <div class="w-8 h-8 rounded-lg bg-green-500"></div>
                  <div class="w-8 h-8 rounded-lg bg-blue-500"></div>
                </div>
                <span class="font-medium text-foreground">RGB 模式</span>
              </div>
              <p class="text-sm text-muted-foreground">
                红 + 绿 + 蓝 = 白色<br/>
                用于屏幕显示、网页、视频
              </p>
            </div>
            
            <div class="bg-secondary rounded-xl p-6">
              <div class="flex items-center gap-4 mb-4">
                <div class="flex gap-2">
                  <div class="w-8 h-8 rounded-lg bg-cyan-500"></div>
                  <div class="w-8 h-8 rounded-lg bg-pink-500"></div>
                  <div class="w-8 h-8 rounded-lg bg-yellow-400"></div>
                  <div class="w-8 h-8 rounded-lg bg-gray-900"></div>
                </div>
                <span class="font-medium text-foreground">CMYK 模式</span>
              </div>
              <p class="text-sm text-muted-foreground">
                青 + 品红 + 黄 + 黑 = 黑色<br/>
                用于印刷、出版、包装
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>
