<script setup lang="ts">
import { computed } from 'vue'
import type { ArticleGraph, GraphNode } from '../api/types'
import { formatDate } from '../utils/format'

const props = defineProps<{ graph: ArticleGraph }>()
const emit = defineEmits<{ openArticle: [articleId: number] }>()

const NODE_LIMIT = 30
const WIDTH = 720
const HEIGHT = 390
const CENTER_X = WIDTH / 2
const CENTER_Y = 185
const RADIUS = 135

const visibleNodes = computed(() => props.graph.nodes.slice(0, NODE_LIMIT))
const visibleNodeIds = computed(() => new Set(visibleNodes.value.map((node) => node.id)))
const visibleEdges = computed(() =>
  props.graph.edges.filter(
    (edge) => visibleNodeIds.value.has(edge.source) && visibleNodeIds.value.has(edge.target),
  ),
)
const reduced = computed(() => props.graph.nodes.length > NODE_LIMIT)
const markerId = computed(() => `arrow-${props.graph.article_id}`)

function position(nodeId: number): { x: number; y: number } {
  const index = visibleNodes.value.findIndex((node) => node.id === nodeId)
  if (visibleNodes.value.length <= 1) return { x: CENTER_X, y: CENTER_Y }
  const angle = (Math.PI * 2 * index) / visibleNodes.value.length - Math.PI / 2
  return {
    x: CENTER_X + Math.cos(angle) * RADIUS,
    y: CENTER_Y + Math.sin(angle) * RADIUS,
  }
}

function shortName(node: GraphNode): string {
  return node.name.length > 10 ? `${node.name.slice(0, 9)}…` : node.name
}
</script>

<template>
  <article class="graph-card">
    <header class="graph-card-header">
      <div>
        <time :datetime="graph.article_service_date">{{ formatDate(graph.article_service_date) }}</time>
        <h3>{{ graph.article_title }}</h3>
      </div>
      <button type="button" @click="emit('openArticle', graph.article_id)">
        출처 기사 #{{ graph.article_id }}
      </button>
    </header>

    <p v-if="reduced" class="graph-reduced">
      노드 {{ graph.nodes.length }}개 중 앞의 {{ NODE_LIMIT }}개만 표시했습니다.
    </p>
    <div v-if="visibleNodes.length" class="graph-canvas">
      <svg :viewBox="`0 0 ${WIDTH} ${HEIGHT}`" role="img" :aria-label="`${graph.article_title} 관계 그래프`">
        <defs>
          <marker
            :id="markerId"
            markerWidth="8"
            markerHeight="8"
            refX="27"
            refY="4"
            orient="auto"
          >
            <path d="M0,0 L8,4 L0,8 z" class="graph-arrow" />
          </marker>
        </defs>
        <g v-for="edge in visibleEdges" :key="edge.id" class="graph-edge">
          <line
            :x1="position(edge.source).x"
            :y1="position(edge.source).y"
            :x2="position(edge.target).x"
            :y2="position(edge.target).y"
            :marker-end="`url(#${markerId})`"
          />
          <text
            :x="(position(edge.source).x + position(edge.target).x) / 2"
            :y="(position(edge.source).y + position(edge.target).y) / 2 - 6"
          >
            {{ edge.type }}
          </text>
        </g>
        <g
          v-for="node in visibleNodes"
          :key="node.id"
          class="graph-node"
          :transform="`translate(${position(node.id).x} ${position(node.id).y})`"
        >
          <circle r="34" />
          <text class="graph-node-name" text-anchor="middle" y="-2">{{ shortName(node) }}</text>
          <text class="graph-node-type" text-anchor="middle" y="14">{{ node.type }}</text>
          <title>{{ node.name }} · {{ node.type }} · 출처 기사 #{{ graph.article_id }}</title>
        </g>
      </svg>
    </div>
    <p v-else class="graph-empty-card">이 기사에서 표시할 엔티티·관계를 찾지 못했습니다.</p>
  </article>
</template>
