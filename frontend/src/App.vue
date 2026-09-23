<script setup>
import { computed, ref, watch } from 'vue'
import AppSidebar from './components/AppSidebar.vue'
import ForecastPanel from './components/ForecastPanel.vue'
import WindMap from './components/WindMap.vue'
import { initialForecastState, turbines, windFarms } from './data/windForecast'
import { messages } from './i18n/messages'

const language = ref(initialForecastState.language)
const selectedWindFarmId = ref(initialForecastState.selectedWindFarmId)
const selectedTurbineId = ref(initialForecastState.selectedTurbineId)
const startDate = ref(initialForecastState.startDate)

const t = computed(() => messages[language.value])
const selectedWindFarm = computed(() =>
  windFarms.find((windFarm) => windFarm.id === selectedWindFarmId.value),
)
const visibleTurbines = computed(() =>
  turbines.filter((turbine) => turbine.windFarmId === selectedWindFarmId.value),
)
const selectedTurbine = computed(() =>
  visibleTurbines.value.find((turbine) => turbine.id === selectedTurbineId.value) ??
  visibleTurbines.value[0],
)

function selectTurbine(turbineId) {
  selectedTurbineId.value = turbineId
}

watch(selectedWindFarmId, () => {
  selectedTurbineId.value = visibleTurbines.value[0]?.id
})
</script>

<template>
  <main class="page-shell">
    <AppSidebar
      v-model:language="language"
      v-model:selected-wind-farm-id="selectedWindFarmId"
      v-model:start-date="startDate"
      :t="t"
      :visible-turbines="visibleTurbines"
      :wind-farms="windFarms"
      @select-turbine="selectTurbine"
    />

    <WindMap
      v-model:selected-turbine-id="selectedTurbineId"
      :language="language"
      :selected-turbine="selectedTurbine"
      :selected-wind-farm="selectedWindFarm"
      :t="t"
      :visible-turbines="visibleTurbines"
    />

    <ForecastPanel :selected-turbine="selectedTurbine" :t="t" />
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

@media (max-width: 880px) {
  .page-shell {
    grid-template-columns: 1fr;
    grid-template-rows: auto;
    height: auto;
    min-height: 100svh;
  }
}
</style>
