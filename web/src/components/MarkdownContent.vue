<script setup lang="ts">
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps<{ source: string }>()

const rendered = computed(() => {
  const html = marked.parse(props.source || '', {
    async: false,
    breaks: true,
    gfm: true,
  })
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true },
  })
})
</script>

<template>
  <!-- DOMPurify로 정화한 HTML만 렌더링한다. -->
  <div class="markdown-body" v-html="rendered"></div>
</template>
