<script setup>
import { computed } from 'vue'
import { CalendarDays, Factory, Languages, RefreshCw, Zap } from '@lucide/vue'
import { useRotatingAgentMessage } from '../composables/useRotatingAgentMessage'
import { languageOptions } from '../i18n/messages'
import { localized } from '../utils/localized'

const props = defineProps({
  bootstrapError: {
    type: String,
    default: '',
  },
  bootstrapStatus: {
    type: String,
    required: true,
  },
  forecastError: {
    type: String,
    default: '',
  },
  forecastStatus: {
    type: String,
    required: true,
  },
  language: {
    type: String,
    required: true,
  },
  selectedWindFarmId: {
    type: String,
    required: true,
  },
  startDate: {
    type: String,
    required: true,
  },
  t: {
    type: Object,
    required: true,
  },
  ticketId: {
    type: String,
    default: '',
  },
  visibleTurbines: {
    type: Array,
    required: true,
  },
  windFarms: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits([
  'retry-bootstrap',
  'select-turbine',
  'update:language',
  'update:selectedWindFarmId',
  'update:startDate',
])

const rotatingAgentStatus = useRotatingAgentMessage(
  computed(() => props.forecastStatus),
  computed(() => props.t),
)

const statusMessage = computed(() => {
  if (props.bootstrapStatus === 'loading') return props.t.loadingBootstrap
  if (props.bootstrapStatus === 'error') return props.bootstrapError
  if (props.forecastStatus === 'idle') return props.t.waitingForSelection
  if (rotatingAgentStatus.message.value) return rotatingAgentStatus.message.value
  if (props.forecastStatus === 'succeeded') return props.t.forecastReady

  return props.forecastError
})
</script>

<template>
  <aside class="sidebar" aria-label="Map controls">
    <header class="brand-block">
      <div class="brand-main">
        <div class="brand-icon">
          <Zap :size="22" />
        </div>
        <div>
          <h1>{{ t.appTitle }}</h1>
          <p>{{ t.subtitle }}</p>
        </div>
      </div>

      <div class="language-switcher">
        <Languages :size="16" />
        <div class="compact-segmented-control" role="group" :aria-label="t.language">
          <button
            v-for="option in languageOptions"
            :key="option.code"
            type="button"
            :class="{ active: language === option.code }"
            @click="emit('update:language', option.code)"
          >
            {{ option.label }}
          </button>
        </div>
      </div>
    </header>

    <section class="control-section">
      <div class="section-title">
        <CalendarDays :size="18" />
        <span>{{ t.calculationStartDate }}</span>
      </div>
      <label class="field">
        <span>{{ t.calculationStartDate }}</span>
        <input
          :value="startDate"
          :disabled="bootstrapStatus !== 'ready'"
          type="date"
          @input="emit('update:startDate', $event.target.value)"
        />
      </label>
      <p class="field-hint">{{ t.calculationStartHint }}</p>
    </section>

    <section class="asset-list">
      <div class="section-title">
        <Factory :size="18" />
        <span>{{ t.windFarmInfo }}</span>
      </div>
      <button
        v-for="turbine in visibleTurbines"
        :key="turbine.id"
        type="button"
        class="asset-item"
        :disabled="bootstrapStatus !== 'ready'"
        @click="emit('select-turbine', turbine.id)"
      >
        <span class="swatch"></span>
        <span>
          <strong>{{ localized(turbine.name, language) }}</strong>
          <small>{{ t.coordinates }}: {{ turbine.coordLabel }}</small>
        </span>
      </button>
    </section>

    <section class="status-section" aria-live="polite">
      <div class="status-row">
        <span
          class="status-dot"
          :class="{
            loading: bootstrapStatus === 'loading' || ['submitting', 'preparing', 'pending'].includes(forecastStatus),
            ready: forecastStatus === 'succeeded',
            error: bootstrapStatus === 'error' || forecastStatus === 'error',
          }"
        ></span>
        <div>
          <strong>{{ t.agentStatus }}</strong>
          <Transition name="status-message" mode="out-in">
            <small :key="statusMessage">{{ statusMessage }}</small>
          </Transition>
        </div>
      </div>

      <div
        v-if="['submitting', 'preparing', 'pending'].includes(forecastStatus)"
        class="agent-steps"
        aria-hidden="true"
      >
        <span></span>
        <span></span>
        <span></span>
      </div>

      <code v-if="ticketId">{{ t.ticket }}: {{ ticketId }}</code>

      <button
        v-if="bootstrapStatus === 'error'"
        type="button"
        class="retry-button"
        @click="emit('retry-bootstrap')"
      >
        <RefreshCw :size="15" />
        {{ t.retry }}
      </button>
    </section>
  </aside>
</template>

<style scoped>
.sidebar {
  grid-row: 1 / 3;
  display: flex;
  flex-direction: column;
  gap: 18px;
  max-height: 100svh;
  padding: 24px;
  background: var(--panel);
  border-right: 1px solid var(--line);
  overflow-y: auto;
}

.brand-block {
  display: grid;
  gap: 16px;
  padding-bottom: 8px;
}

.brand-main {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.brand-icon {
  display: grid;
  flex: 0 0 42px;
  width: 42px;
  height: 42px;
  place-items: center;
  color: #ffffff;
  background: var(--accent);
  border-radius: 8px;
  box-shadow: 0 10px 22px rgba(21, 122, 101, 0.24);
}

h1 {
  margin: 0 0 5px;
  font-size: 26px;
  line-height: 1.1;
  letter-spacing: 0;
}

p {
  margin: 0;
  color: var(--muted);
  line-height: 1.45;
}

.language-switcher {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 6px;
  color: var(--muted);
  background: var(--panel-strong);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.compact-segmented-control {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 3px;
  flex: 1;
  max-width: 210px;
  padding: 3px;
  background: #edf1ef;
  border-radius: 7px;
}

.compact-segmented-control button {
  min-height: 30px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 850;
}

.compact-segmented-control button.active {
  color: var(--accent);
  background: #ffffff;
  box-shadow: 0 5px 13px rgba(34, 47, 42, 0.1);
}

.control-section,
.asset-list {
  display: grid;
  gap: 12px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.field-hint {
  color: var(--muted);
  font-size: 13px;
  line-height: 1.4;
}

.asset-list {
  flex: 1;
  align-content: start;
}

.asset-item {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 11px;
  width: 100%;
  padding: 11px;
  text-align: left;
  background: var(--panel-strong);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  transition:
    border-color 0.18s ease,
    transform 0.18s ease,
    background 0.18s ease;
}

.asset-item:hover {
  background: #ffffff;
  border-color: rgba(21, 122, 101, 0.34);
  transform: translateY(-1px);
}

.asset-item:disabled,
select:disabled,
input:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.asset-item strong,
.asset-item small {
  display: block;
}

.asset-item strong {
  overflow: hidden;
  color: var(--text);
  font-size: 14px;
  line-height: 1.28;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-item small {
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
}

.swatch {
  flex: 0 0 10px;
  width: 10px;
  height: 10px;
  background: #1c9f88;
  border-radius: 999px;
  box-shadow: 0 0 0 3px rgba(255, 255, 255, 0.8);
}

.status-section {
  display: grid;
  gap: 10px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}

.status-row {
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 10px;
  align-items: start;
}

.status-dot {
  width: 10px;
  height: 10px;
  margin-top: 5px;
  background: #9aa6a0;
  border-radius: 999px;
}

.status-dot.loading {
  background: #d5961f;
  animation: pulse 1s ease-in-out infinite;
}

.status-dot.ready {
  background: var(--accent);
}

.status-dot.error {
  background: #c84d3c;
}

.status-row strong,
.status-row small {
  display: block;
}

.status-row strong {
  color: var(--text);
  font-size: 13px;
  line-height: 1.3;
}

.status-row small {
  margin-top: 3px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.agent-steps {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 5px;
  height: 5px;
}

.agent-steps span {
  background: linear-gradient(90deg, rgba(21, 122, 101, 0.2), rgba(21, 122, 101, 0.86));
  border-radius: 999px;
  transform-origin: left center;
  animation: agentStep 1.35s ease-in-out infinite;
}

.agent-steps span:nth-child(2) {
  animation-delay: 0.16s;
}

.agent-steps span:nth-child(3) {
  animation-delay: 0.32s;
}

.status-message-enter-active,
.status-message-leave-active {
  transition:
    opacity 0.22s ease,
    transform 0.22s ease;
}

.status-message-enter-from {
  opacity: 0;
  transform: translateY(5px);
}

.status-message-leave-to {
  opacity: 0;
  transform: translateY(-5px);
}

.status-section code {
  display: block;
  overflow: hidden;
  padding: 8px 9px;
  color: #34413d;
  background: #eef3f0;
  border: 1px solid var(--line);
  border-radius: 7px;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.retry-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-height: 36px;
  color: #ffffff;
  background: var(--accent);
  border: 0;
  border-radius: 7px;
  font-size: 12px;
  font-weight: 800;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 0.45;
    transform: scale(0.9);
  }

  50% {
    opacity: 1;
    transform: scale(1.12);
  }
}

@keyframes agentStep {
  0%,
  100% {
    opacity: 0.42;
    transform: scaleX(0.36);
  }

  50% {
    opacity: 1;
    transform: scaleX(1);
  }
}

@media (max-width: 880px) {
  .sidebar {
    grid-row: auto;
    max-height: none;
    min-height: auto;
    border-right: 0;
    border-bottom: 1px solid var(--line);
  }

  .asset-list {
    max-height: 250px;
    overflow-y: auto;
  }
}

@media (max-width: 520px) {
  .sidebar {
    padding: 18px;
  }

  .brand-main {
    gap: 11px;
  }

  h1 {
    font-size: 22px;
  }
}
</style>
