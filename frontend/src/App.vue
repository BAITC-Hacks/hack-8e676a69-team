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
import { localized } from './utils/localized'

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
const confirmationOpen = ref(false)

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
const selectedTurbineName = computed(() =>
  selectedTurbine.value ? localized(selectedTurbine.value.name, language.value) : '',
)
const canConfirmForecast = computed(() =>
  bootstrapStatus.value === 'ready' && Boolean(selectedTurbine.value) && Boolean(startDate.value),
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
  confirmationOpen.value = false

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
    requestForecastConfirmation()
  } catch (error) {
    autoSubmitPaused = false
    bootstrapStatus.value = 'error'
    bootstrapError.value = error.message
  }
}

function scheduleForecast() {
  if (autoSubmitPaused || bootstrapStatus.value !== 'ready') return

  window.clearTimeout(submitTimer)
  submitTimer = window.setTimeout(requestForecastConfirmation, 350)
}

function requestForecastConfirmation() {
  if (!canConfirmForecast.value) return

  confirmationOpen.value = true
  forecastStatus.value = 'awaiting-confirmation'
  forecastError.value = ''
  currentTicket.value = null
}

function cancelForecastConfirmation() {
  confirmationOpen.value = false

  if (forecastStatus.value === 'awaiting-confirmation') {
    forecastStatus.value = 'idle'
  }
}

function confirmForecast() {
  if (!canConfirmForecast.value) return

  confirmationOpen.value = false
  submitForecast()
}

async function submitForecast() {
  const turbine = selectedTurbine.value

  if (!turbine || !startDate.value) return

  confirmationOpen.value = false
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

    <Teleport to="body">
      <Transition name="modal-fade">
        <div
          v-if="confirmationOpen"
          class="confirmation-backdrop"
          role="presentation"
          @click.self="cancelForecastConfirmation"
        >
          <section
            class="confirmation-dialog"
            role="dialog"
            aria-modal="true"
            :aria-labelledby="'forecast-confirm-title'"
            @keydown.esc="cancelForecastConfirmation"
          >
            <h2 id="forecast-confirm-title">{{ t.confirmForecastTitle }}</h2>
            <p>{{ t.confirmForecastDescription }}</p>

            <dl class="confirmation-details">
              <div>
                <dt>{{ t.confirmForecastTurbine }}</dt>
                <dd>{{ selectedTurbineName }}</dd>
              </div>
              <div>
                <dt>{{ t.confirmForecastStartDate }}</dt>
                <dd>{{ startDate }}</dd>
              </div>
            </dl>

            <div class="confirmation-actions">
              <button type="button" class="secondary-action" @click="cancelForecastConfirmation">
                {{ t.confirmForecastCancel }}
              </button>
              <button type="button" class="primary-action" :disabled="!canConfirmForecast" @click="confirmForecast">
                {{ t.confirmForecastSubmit }}
              </button>
            </div>
          </section>
        </div>
      </Transition>
    </Teleport>
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

.confirmation-backdrop {
  position: fixed;
  z-index: 1200;
  inset: 0;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgba(24, 33, 31, 0.42);
  backdrop-filter: blur(3px);
}

.confirmation-dialog {
  display: grid;
  gap: 16px;
  width: min(100%, 420px);
  padding: 22px;
  background: #ffffff;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

.confirmation-dialog h2 {
  margin: 0;
  color: var(--text);
  font-size: 21px;
  line-height: 1.2;
  letter-spacing: 0;
}

.confirmation-dialog p {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.45;
}

.confirmation-details {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 12px;
  background: var(--panel-strong);
  border: 1px solid var(--line);
  border-radius: var(--radius);
}

.confirmation-details div {
  display: grid;
  grid-template-columns: minmax(120px, 0.85fr) minmax(0, 1fr);
  gap: 12px;
  align-items: center;
}

.confirmation-details dt {
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.confirmation-details dd {
  min-width: 0;
  margin: 0;
  color: var(--text);
  font-size: 13px;
  font-weight: 800;
  overflow-wrap: anywhere;
}

.confirmation-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.confirmation-actions button {
  min-height: 38px;
  padding: 0 14px;
  border-radius: 7px;
  font-size: 13px;
  font-weight: 850;
}

.secondary-action {
  color: var(--text);
  background: #ffffff;
  border: 1px solid var(--line);
}

.primary-action {
  color: #ffffff;
  background: var(--accent);
  border: 1px solid var(--accent);
}

.primary-action:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.modal-fade-enter-active,
.modal-fade-leave-active {
  transition: opacity 0.18s ease;
}

.modal-fade-enter-active .confirmation-dialog,
.modal-fade-leave-active .confirmation-dialog {
  transition: transform 0.18s ease;
}

.modal-fade-enter-from,
.modal-fade-leave-to {
  opacity: 0;
}

.modal-fade-enter-from .confirmation-dialog,
.modal-fade-leave-to .confirmation-dialog {
  transform: translateY(8px) scale(0.98);
}

@media (max-width: 880px) {
  .page-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
    height: auto;
    min-height: 100svh;
  }
}

@media (max-width: 520px) {
  .confirmation-dialog {
    padding: 18px;
  }

  .confirmation-details div {
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .confirmation-actions {
    display: grid;
    grid-template-columns: 1fr;
  }
}
</style>
