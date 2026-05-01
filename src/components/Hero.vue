<script setup lang="ts">
import { ArrowDown } from 'lucide-vue-next'
</script>

<template>
  <section class="py-20 md:py-32 px-6 md:px-12 text-center">
    <div class="max-w-4xl mx-auto animate-fade-in">
      <div class="inline-flex items-center gap-2 bg-secondary px-4 py-2 rounded-full mb-8">
        <span class="w-2 h-2 bg-accent rounded-full animate-pulse-soft"></span>
        <span class="text-sm text-muted-foreground">专业印刷色彩转换</span>
      </div>
      
      <h1 class="text-4xl md:text-6xl lg:text-7xl font-serif font-medium tracking-tight text-foreground leading-tight">
        RGB 到 CMYK
        <br />
        <span class="text-muted-foreground">专业级转换</span>
      </h1>
      
      <p class="mt-8 text-lg md:text-xl text-muted-foreground max-w-2xl mx-auto leading-relaxed">
        将 AI 生成的 RGB 图片一键转换为印刷级 CMYK PDF 文件，
        确保色彩准确，满足印刷厂的专业要求
      </p>
      
      <div class="mt-12 flex flex-col sm:flex-row items-center justify-center gap-4">
        <a 
          href="#converter" 
          class="btn-primary bg-primary text-primary-foreground px-8 py-4 rounded-xl text-base font-medium flex items-center gap-2"
        >
          立即开始
          <ArrowDown class="w-4 h-4" />
        </a>
        <a 
          href="#features" 
          class="px-8 py-4 rounded-xl text-base font-medium text-muted-foreground hover:text-foreground transition-colors"
        >
          了解更多
        </a>
      </div>
    </div>
    
    <!-- Decorative Elements -->
    <div class="mt-20 flex items-center justify-center gap-8">
      <div class="flex items-center gap-3">
        <div class="w-12 h-12 rounded-xl bg-red-100 flex items-center justify-center">
          <span class="text-red-600 font-mono text-xs font-bold">R</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-green-100 flex items-center justify-center">
          <span class="text-green-600 font-mono text-xs font-bold">G</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-blue-100 flex items-center justify-center">
          <span class="text-blue-600 font-mono text-xs font-bold">B</span>
        </div>
      </div>
      
      <div class="text-muted-foreground">→</div>
      
      <div class="flex items-center gap-3">
        <div class="w-12 h-12 rounded-xl bg-cyan-100 flex items-center justify-center">
          <span class="text-cyan-600 font-mono text-xs font-bold">C</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-pink-100 flex items-center justify-center">
          <span class="text-pink-600 font-mono text-xs font-bold">M</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-yellow-100 flex items-center justify-center">
          <span class="text-yellow-600 font-mono text-xs font-bold">Y</span>
        </div>
        <div class="w-12 h-12 rounded-xl bg-gray-200 flex items-center justify-center">
          <span class="text-gray-700 font-mono text-xs font-bold">K</span>
        </div>
      </div>
    </div>
  </section>
</template>
