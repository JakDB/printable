<script setup lang="ts">
import { Palette } from 'lucide-vue-next'
</script>

<template>
  <header class="w-full py-6 px-6 md:px-12 flex items-center justify-between border-b border-border">
    <div class="flex items-center gap-3">
      <div class="w-10 h-10 bg-primary rounded-xl flex items-center justify-center">
        <Palette class="w-5 h-5 text-primary-foreground" />
      </div>
      <span class="text-xl font-semibold tracking-tight text-foreground">Printable</span>
    </div>
    
    <nav class="hidden md:flex items-center gap-8">
      <a href="#converter" class="text-muted-foreground hover:text-foreground transition-colors text-sm">
        转换工具
      </a>
      <a href="#features" class="text-muted-foreground hover:text-foreground transition-colors text-sm">
        功能特点
      </a>
    </nav>
    
    <a 
      href="#converter" 
      class="btn-primary bg-primary text-primary-foreground px-5 py-2.5 rounded-xl text-sm font-medium"
    >
      开始转换
    </a>
  </header>
</template>
