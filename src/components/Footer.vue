<script setup lang="ts">
import { Palette } from 'lucide-vue-next'
</script>

<template>
  <footer class="py-12 px-6 md:px-12 border-t border-border">
    <div class="max-w-6xl mx-auto flex flex-col md:flex-row items-center justify-between gap-6">
      <div class="flex items-center gap-3">
        <div class="w-8 h-8 bg-primary rounded-lg flex items-center justify-center">
          <Palette class="w-4 h-4 text-primary-foreground" />
        </div>
        <span class="font-medium text-foreground">Printable</span>
      </div>
      
      <p class="text-sm text-muted-foreground text-center">
        专业 RGB 到 CMYK 色彩转换工具 · 为印刷而生
      </p>
      
      <p class="text-sm text-muted-foreground">
        © {{ new Date().getFullYear() }} Printable
      </p>
    </div>
  </footer>
</template>
