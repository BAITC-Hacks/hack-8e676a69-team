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
  selectedTurbineId.value = turbineId
}

function clearPolling() {
  window.clearTimeout(submitTimer)
  window.clearTimeout(pollTimer)
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
      pollTimer = window.setTimeout(
        () => pollTicket(ticketId, turbineId, serial),
        response.poll_after_ms ?? pollIntervalMs.value,
      )
      return
    }

    rawForecast.value = response
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
  }
}

watch(selectedWindFarmId, () => {
  selectedTurbineId.value = visibleTurbines.value[0]?.id
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
      :t="t"
      :ticket-id="currentTicket?.ticket_id"
      :visible-turbines="visibleTurbines"
      :wind-farms="windFarms"
      @retry-bootstrap="loadBootstrap"
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
