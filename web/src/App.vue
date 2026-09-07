<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
</script>

<template>
  <div class="app-shell">
    <header class="site-header">
      <RouterLink class="brand" to="/" aria-label="NewsTrace 이슈 목록">
        <span class="brand-mark" aria-hidden="true">N</span>
        <span>
          <strong>NewsTrace</strong>
          <small>evidence-led timelines</small>
        </span>
      </RouterLink>
      <p class="header-note">기사에서 시작해 사건의 흐름을 읽습니다</p>
    </header>

    <RouterView />

    <footer class="site-footer">
      <span>NewsTrace</span>
      <span>모든 사건은 연결된 기사 근거와 함께 표시됩니다.</span>
    </footer>
  </div>
</template>
