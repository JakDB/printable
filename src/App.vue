<script setup lang="ts">
import Header from './components/Header.vue'
import Hero from './components/Hero.vue'
import Converter from './components/Converter.vue'
import Features from './components/Features.vue'
import Footer from './components/Footer.vue'
</script>

<template>
  <div class="min-h-screen bg-background flex flex-col">
    <Header />
    <main class="flex-1">
      <Hero />
      <Converter />
      <Features />
    </main>
    <Footer />
  </div>
</template>
