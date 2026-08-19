<!--
  Nombre de archivo: AccordionItem.vue
  Ubicación de archivo: web/frontend/src/components/infra/AccordionItem.vue
  Descripción: Acordeón reutilizable con transición de altura dinámica para modales y paneles del frontend
-->
<template>
  <article :class="['accordion-item', { 'is-open': modelValue }]">
    <button
      class="accordion-trigger"
      type="button"
      :aria-expanded="modelValue"
      @click="toggle"
    >
      <div class="accordion-heading">
        <p v-if="eyebrow" class="accordion-eyebrow">{{ eyebrow }}</p>
        <strong class="accordion-title">{{ title }}</strong>
        <span v-if="description" class="accordion-description">{{ description }}</span>
      </div>
      <div class="accordion-side">
        <slot name="meta" />
        <span class="accordion-icon" aria-hidden="true">{{ modelValue ? '−' : '+' }}</span>
      </div>
    </button>

    <Transition
      @before-enter="beforeEnter"
      @enter="enter"
      @after-enter="afterEnter"
      @before-leave="beforeLeave"
      @leave="leave"
      @after-leave="afterLeave"
    >
      <div v-if="modelValue" class="accordion-panel">
        <div class="accordion-panel__inner">
          <slot />
        </div>
      </div>
    </Transition>
  </article>
</template>

<script setup lang="ts">
const props = defineProps<{
  modelValue: boolean;
  title: string;
  description?: string;
  eyebrow?: string;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: boolean];
}>();

function toggle(): void {
  emit('update:modelValue', !props.modelValue);
}

function beforeEnter(element: Element): void {
  const target = element as HTMLElement;
  target.style.height = '0';
  target.style.opacity = '0';
  target.style.transform = 'translateY(-6px)';
  target.style.overflow = 'hidden';
}

function enter(element: Element): void {
  const target = element as HTMLElement;
  target.style.transition = 'height 220ms ease, opacity 180ms ease, transform 220ms ease';
  void target.offsetHeight;
  requestAnimationFrame(() => {
    target.style.height = `${target.scrollHeight}px`;
    target.style.opacity = '1';
    target.style.transform = 'translateY(0)';
  });
}

function afterEnter(element: Element): void {
  const target = element as HTMLElement;
  target.style.height = 'auto';
  target.style.overflow = 'visible';
  target.style.transition = '';
}

function beforeLeave(element: Element): void {
  const target = element as HTMLElement;
  target.style.height = `${target.scrollHeight}px`;
  target.style.opacity = '1';
  target.style.transform = 'translateY(0)';
  target.style.overflow = 'hidden';
}

function leave(element: Element): void {
  const target = element as HTMLElement;
  target.style.transition = 'height 220ms ease, opacity 160ms ease, transform 220ms ease';
  void target.offsetHeight;
  requestAnimationFrame(() => {
    target.style.height = '0';
    target.style.opacity = '0';
    target.style.transform = 'translateY(-6px)';
  });
}

function afterLeave(element: Element): void {
  const target = element as HTMLElement;
  target.style.transition = '';
  target.style.height = '';
  target.style.opacity = '';
  target.style.transform = '';
  target.style.overflow = '';
}
</script>

<style scoped>
.accordion-item {
  border-radius: 16px;
  border: 1px solid var(--color-divider);
  background: var(--color-bg);
  overflow: hidden;
}

.accordion-item.is-open {
  border-color: var(--color-accent);
  box-shadow: var(--shadow-sm);
}

.accordion-trigger {
  width: 100%;
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  padding: 18px;
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.accordion-trigger:hover .accordion-title {
  color: var(--color-text);
}

.accordion-trigger:focus-visible {
  outline: 2px solid var(--color-accent);
  outline-offset: -2px;
}

.accordion-heading {
  display: grid;
  gap: 6px;
}

.accordion-eyebrow {
  margin: 0;
  color: var(--color-accent);
  font-size: 0.72rem;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.accordion-title {
  color: var(--color-neutral-200);
  font-size: 0.98rem;
  line-height: 1.45;
}

.accordion-description {
  color: var(--muted);
  font-size: 0.82rem;
}

.accordion-side {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.accordion-icon {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: var(--color-brand-primary-soft);
  color: var(--color-accent-200);
  font-size: 1.1rem;
  font-weight: 700;
}

.accordion-panel {
  will-change: height, opacity, transform;
}

.accordion-panel__inner {
  padding: 0 18px 18px;
  border-top: 1px solid var(--color-divider);
}

@media (max-width: 720px) {
  .accordion-trigger {
    flex-direction: column;
  }

  .accordion-side {
    width: 100%;
    justify-content: space-between;
  }
}
</style>