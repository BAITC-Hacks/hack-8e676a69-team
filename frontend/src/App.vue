<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { fetchBootstrap, createForecastTicket, pollForecastTicket } from './api/forecastApi'
import AppSidebar from './components/AppSidebar.vue'
import ForecastPanel from './components/ForecastPanel.vue'
import WindMap from './components/WindMap.vue'
import { messages } from './i18n/messages'
import {
  applyForecastToTurbines,
  normalizeBootstrap,
  normalizeForecastResponse,
} from './utils/backendForecast'

const REQUEST_HISTORY_STORAGE_KEY = 'windForecast.requestHistory.v1'
const REQUEST_HISTORY_LIMIT = 50

const language = ref('ru')
const windFarms = ref([])
const turbines = ref([])
const selectedWindFarmId = ref('')
const selectedTurbineId = ref('')
const startDate = ref('')
const historyDays = ref(30)
const predictionHours = ref(48)
const pollIntervalMs = ref(1000)
const bootstrapStatus = ref('loading')
const bootstrapError = ref('')
const forecastStatus = ref('idle')
const forecastError = ref('')
const currentTicket = ref(null)
const rawForecast = ref(null)
const requestHistory = ref(loadRequestHistory())
const selectedHistoryTicketId = ref('')

let autoSubmitPaused = false
let submitTimer
let pollTimer
let requestSerial = 0

const t = computed(() => messages[language.value])
const selectedWindFarm = computed(() =>
  windFarms.value.find((windFarm) => windFarm.id === selectedWindFarmId.value) ?? windFarms.value[0],
)
const visibleTurbines = computed(() =>
  turbines.value.filter((turbine) => turbine.windFarmId === selectedWindFarmId.value),
)
const selectedTurbine = computed(() =>
  visibleTurbines.value.find((turbine) => turbine.id === selectedTurbineId.value) ??
  visibleTurbines.value[0],
)

function selectTurbine(turbineId) {
  selectedHistoryTicketId.value = ''
  selectedTurbineId.value = turbineId
}

function clearPolling() {
  window.clearTimeout(submitTimer)
  window.clearTimeout(pollTimer)
}

function loadRequestHistory() {
  if (typeof window === 'undefined') return []

  try {
    const saved = JSON.parse(window.localStorage.getItem(REQUEST_HISTORY_STORAGE_KEY) ?? '[]')

    return Array.isArray(saved)
      ? saved
          .filter((entry) => entry?.ticketId)
          .sort((a, b) => Date.parse(b.updatedAt ?? b.createdAt) - Date.parse(a.updatedAt ?? a.createdAt))
      : []
  } catch {
    return []
  }
}

function persistRequestHistory() {
  if (typeof window === 'undefined') return

  try {
    window.localStorage.setItem(REQUEST_HISTORY_STORAGE_KEY, JSON.stringify(requestHistory.value))
  } catch {
    // Keep the in-memory history if localStorage is unavailable or full.
  }
}

function upsertRequestHistory(ticketId, patch) {
  if (!ticketId) return

  const existing = requestHistory.value.find((entry) => entry.ticketId === ticketId)
  const updated = {
    ...(existing ?? {}),
    ...patch,
    ticketId,
    updatedAt: new Date().toISOString(),
  }

  requestHistory.value = [
    updated,
    ...requestHistory.value.filter((entry) => entry.ticketId !== ticketId),
  ].slice(0, REQUEST_HISTORY_LIMIT)
  persistRequestHistory()
}

async function selectHistoryTicket(ticketId) {
  const entry = requestHistory.value.find((item) => item.ticketId === ticketId)

  if (!entry) return

  requestSerial += 1
  clearPolling()
  autoSubmitPaused = true
  selectedHistoryTicketId.value = ticketId
  forecastError.value = entry.errorMessage ?? ''
  currentTicket.value = {
    ...(entry.ticket ?? {}),
    ticket_id: ticketId,
    status: entry.status === 'done' ? 'done' : entry.status,
  }
  rawForecast.value = entry.response ?? null

  const turbine = turbines.value.find(
    (item) => item.backendId === entry.turbineId || item.id === entry.turbineId,
  )

  if (turbine) {
    selectedWindFarmId.value = turbine.windFarmId
    selectedTurbineId.value = turbine.id
  }

  if (entry.horizonStart) startDate.value = entry.horizonStart
  if (entry.historyDays) historyDays.value = entry.historyDays

  if (entry.status === 'done' && entry.response && turbine) {
    turbines.value = applyForecastToTurbines(
      turbines.value,
      entry.turbineId,
      normalizeForecastResponse(entry.response, t.value.agentNames),
    )
    forecastStatus.value = 'succeeded'
  } else if (entry.status === 'error') {
    forecastStatus.value = 'error'
  } else {
    forecastStatus.value = entry.status ?? 'pending'
  }

  await nextTick()
  autoSubmitPaused = false
}

async function loadBootstrap() {
  autoSubmitPaused = true
  clearPolling()
  bootstrapStatus.value = 'loading'
  bootstrapError.value = ''
  forecastStatus.value = 'idle'
  forecastError.value = ''
  currentTicket.value = null
  rawForecast.value = null

  try {
    const bootstrap = normalizeBootstrap(await fetchBootstrap())
    windFarms.value = bootstrap.windFarms
    turbines.value = bootstrap.turbines
    selectedWindFarmId.value = bootstrap.windFarms[0]?.id ?? ''
    selectedTurbineId.value = bootstrap.defaults.turbine_id ?? bootstrap.turbines[0]?.id ?? ''
    startDate.value = bootstrap.defaults.horizon_start
    historyDays.value = bootstrap.defaults.history_days
    predictionHours.value = bootstrap.predictionHours
    pollIntervalMs.value = bootstrap.pollIntervalMs
    bootstrapStatus.value = 'ready'
    await nextTick()
    autoSubmitPaused = false
    submitForecast()
  } catch (error) {
    autoSubmitPaused = false
    bootstrapStatus.value = 'error'
    bootstrapError.value = error.message
  }
}

function scheduleForecast() {
  if (autoSubmitPaused || bootstrapStatus.value !== 'ready') return

  window.clearTimeout(submitTimer)
  submitTimer = window.setTimeout(submitForecast, 350)
}

async function submitForecast() {
  const turbine = selectedTurbine.value

  if (!turbine || !startDate.value) return

  const serial = ++requestSerial
  clearPolling()
  selectedHistoryTicketId.value = ''
  forecastStatus.value = 'submitting'
  forecastError.value = ''
  rawForecast.value = null
  currentTicket.value = null

  try {
    const ticket = await createForecastTicket({
      turbine_id: turbine.backendId ?? turbine.id,
      horizon_start: startDate.value,
      history_days: historyDays.value,
    })

    if (serial !== requestSerial) return

    currentTicket.value = ticket
    selectedHistoryTicketId.value = ticket.ticket_id
    upsertRequestHistory(ticket.ticket_id, {
      status: ticket.status ?? 'preparing',
      ticket,
      turbineId: turbine.backendId ?? turbine.id,
      turbineName: turbine.name,
      windFarmId: turbine.windFarmId,
      horizonStart: startDate.value,
      historyDays: historyDays.value,
      createdAt: new Date().toISOString(),
      response: null,
      errorMessage: '',
    })
    forecastStatus.value = ticket.status ?? 'preparing'
    pollTimer = window.setTimeout(
      () => pollTicket(ticket.ticket_id, turbine.backendId ?? turbine.id, serial),
      pollIntervalMs.value,
    )
  } catch (error) {
    if (serial !== requestSerial) return
    forecastStatus.value = 'error'
    forecastError.value = error.message
  }
}

async function pollTicket(ticketId, turbineId, serial) {
  try {
    const response = await pollForecastTicket(ticketId)

    if (serial !== requestSerial) return

    if (response?.status === 'preparing' || response?.status === 'pending') {
      forecastStatus.value = response.status
      currentTicket.value = { ...(currentTicket.value ?? {}), ...response }
      upsertRequestHistory(ticketId, {
        status: response.status,
        ticket: currentTicket.value,
        errorMessage: '',
      })
      pollTimer = window.setTimeout(
        () => pollTicket(ticketId, turbineId, serial),
        response.poll_after_ms ?? pollIntervalMs.value,
      )
      return
    }

    rawForecast.value = response
    upsertRequestHistory(ticketId, {
      status: 'done',
      ticket: { ...(currentTicket.value ?? {}), ticket_id: ticketId, status: 'done' },
      response,
      errorMessage: '',
    })
    turbines.value = applyForecastToTurbines(
      turbines.value,
      turbineId,
      normalizeForecastResponse(response, t.value.agentNames),
    )
    forecastStatus.value = 'succeeded'
  } catch (error) {
    if (serial !== requestSerial) return
    forecastStatus.value = 'error'
    forecastError.value = error.message
    upsertRequestHistory(ticketId, {
      status: 'error',
      errorMessage: error.message,
      ticket: { ...(currentTicket.value ?? {}), ticket_id: ticketId, status: 'error' },
    })
  }
}

watch(selectedWindFarmId, () => {
  if (!visibleTurbines.value.some((turbine) => turbine.id === selectedTurbineId.value)) {
    selectedTurbineId.value = visibleTurbines.value[0]?.id
  }
})

watch([selectedTurbineId, startDate], scheduleForecast)

onMounted(loadBootstrap)

onBeforeUnmount(() => {
  requestSerial += 1
  clearPolling()
})
</script>

<template>
  <main class="page-shell">
    <AppSidebar
      v-model:language="language"
      v-model:selected-wind-farm-id="selectedWindFarmId"
      v-model:start-date="startDate"
      :bootstrap-error="bootstrapError"
      :bootstrap-status="bootstrapStatus"
      :forecast-error="forecastError"
      :forecast-status="forecastStatus"
      :request-history="requestHistory"
      :selected-history-ticket-id="selectedHistoryTicketId"
      :t="t"
      :ticket-id="currentTicket?.ticket_id"
      :visible-turbines="visibleTurbines"
      :wind-farms="windFarms"
      @retry-bootstrap="loadBootstrap"
      @select-history="selectHistoryTicket"
      @select-turbine="selectTurbine"
    />

    <WindMap
      v-if="selectedWindFarm && selectedTurbine"
      v-model:start-date="startDate"
      v-model:selected-turbine-id="selectedTurbineId"
      :bootstrap-status="bootstrapStatus"
      :language="language"
      :selected-turbine="selectedTurbine"
      :selected-wind-farm="selectedWindFarm"
      :t="t"
      :visible-turbines="visibleTurbines"
    />
    <section v-else class="map-placeholder">
      <span>{{ bootstrapStatus === 'loading' ? t.loadingBootstrap : t.bootstrapUnavailable }}</span>
    </section>

    <ForecastPanel
      v-if="selectedTurbine"
      :forecast-error="forecastError"
      :forecast-status="forecastStatus"
      :prediction-hours="predictionHours"
      :raw-forecast="rawForecast"
      :selected-turbine="selectedTurbine"
      :t="t"
      :ticket-id="currentTicket?.ticket_id"
    />
  </main>
</template>

<style scoped>
.page-shell {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  grid-template-rows: minmax(0, 1fr) auto;
  height: 100svh;
  min-height: 680px;
}

.map-placeholder {
  display: grid;
  min-width: 0;
  min-height: 0;
  place-items: center;
  color: var(--muted);
  background: #dce6e1;
  font-size: 14px;
  font-weight: 800;
}

@media (max-width: 880px) {
  .page-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
    height: auto;
    min-height: 100svh;
  }
}
</style>
