<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import L from 'leaflet'
import { MapPin, Wind } from '@lucide/vue'
import { localized } from '../utils/localized'

const props = defineProps({
  language: {
    type: String,
    required: true,
  },
  selectedTurbine: {
    type: Object,
    required: true,
  },
  selectedTurbineId: {
    type: String,
    required: true,
  },
  selectedWindFarm: {
    type: Object,
    required: true,
  },
  t: {
    type: Object,
    required: true,
  },
  visibleTurbines: {
    type: Array,
    required: true,
  },
})

const emit = defineEmits(['update:selectedTurbineId'])

const mapElement = ref(null)
let map
let windFarmLayer
let turbineLayer

function renderWindFarm() {
  if (!map || !windFarmLayer) return

  windFarmLayer.clearLayers()

  const marker = L.circleMarker(props.selectedWindFarm.coords, {
    radius: 15,
    color: '#ffffff',
    weight: 3,
    fillColor: '#157a65',
    fillOpacity: 0.35,
    className: 'wind-farm-marker',
  })

  marker.bindPopup(`
    <strong>${localized(props.selectedWindFarm.name, props.language)}</strong>
    <span>${props.t.region}: ${localized(props.selectedWindFarm.region, props.language)}</span>
    <span>${props.t.coordinates}: ${props.selectedWindFarm.coordLabel}</span>
  `)

  marker.addTo(windFarmLayer)
}

function renderTurbines() {
  if (!map || !turbineLayer) return

  turbineLayer.clearLayers()

  props.visibleTurbines.forEach((turbine) => {
    const isSelected = turbine.id === props.selectedTurbineId
    const marker = L.circleMarker(turbine.coords, {
      radius: isSelected ? 12 : 9,
      color: isSelected ? '#18211f' : '#ffffff',
      weight: isSelected ? 3 : 2,
      fillColor: '#157a65',
      fillOpacity: 0.95,
      className: 'turbine-marker',
    })

    marker.bindPopup(`
      <strong>${localized(turbine.name, props.language)}</strong>
      <span>${props.t.coordinates}: ${turbine.coordLabel}</span>
      <span>${props.t.horizon}: ${props.selectedWindFarm.horizon}</span>
    `)

    marker.on('click', () => emit('update:selectedTurbineId', turbine.id))
    marker.addTo(turbineLayer)
  })
}

function flyToWindFarm() {
  if (!map) return
  map.flyTo(props.selectedWindFarm.coords, 12, { duration: 0.8 })
}

function flyToTurbine() {
  if (!map || !props.selectedTurbine) return
  map.flyTo(props.selectedTurbine.coords, 14, { duration: 0.8 })
}

onMounted(async () => {
  await nextTick()

  map = L.map(mapElement.value, {
    center: props.selectedWindFarm.coords,
    zoom: 12,
    minZoom: 5,
    maxZoom: 16,
    zoomControl: false,
  })

  L.control.zoom({ position: 'bottomright' }).addTo(map)

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map)

  windFarmLayer = L.layerGroup().addTo(map)
  turbineLayer = L.layerGroup().addTo(map)
  renderWindFarm()
  renderTurbines()
})

watch(() => [props.language, props.selectedWindFarm.id], () => {
  renderWindFarm()
  renderTurbines()
})

watch(() => props.selectedTurbineId, () => {
  renderTurbines()
  flyToTurbine()
})

watch(() => props.selectedWindFarm.id, flyToWindFarm)

onBeforeUnmount(() => {
  map?.remove()
})

defineExpose({
  flyToWindFarm,
  flyToTurbine,
})
</script>

<template>
  <section class="map-panel" :aria-label="t.mapTitle">
    <div class="map-topbar">
      <label class="turbine-select">
        <span>
          <Wind :size="18" />
          {{ t.turbineLabel }}
        </span>
        <select
          :value="selectedTurbineId"
          @change="emit('update:selectedTurbineId', $event.target.value)"
        >
          <option v-for="turbine in visibleTurbines" :key="turbine.id" :value="turbine.id">
            {{ localized(turbine.name, language) }}
          </option>
        </select>
      </label>

      <div class="turbine-meta" aria-live="polite">
        <span>{{ t.coordinates }}: {{ selectedTurbine.coordLabel }}</span>
        <span>{{ t.horizon }}: {{ selectedWindFarm.horizon }}</span>
        <span>{{ t.testPeriod }}: {{ selectedWindFarm.testPeriod }}</span>
      </div>
    </div>

    <div ref="mapElement" class="map-canvas"></div>

    <div class="map-status">
      <MapPin :size="16" />
      <span>{{ visibleTurbines.length }} {{ t.turbines }} {{ t.shown }}</span>
    </div>
  </section>
</template>

<style scoped>
.map-panel {
  position: relative;
  min-width: 0;
  min-height: 0;
  background: #dce6e1;
}

.map-canvas {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.map-topbar {
  position: absolute;
  z-index: 500;
  top: 18px;
  right: 18px;
  left: 18px;
  display: flex;
  align-items: center;
  gap: 12px;
  max-width: 980px;
  padding: 12px;
  background: rgba(255, 255, 255, 0.93);
  border: 1px solid rgba(217, 224, 220, 0.9);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
  backdrop-filter: blur(12px);
}

.turbine-select {
  display: grid;
  flex: 1 1 300px;
  gap: 6px;
  min-width: 240px;
}

.turbine-select > span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  color: #34413d;
  font-size: 13px;
  font-weight: 800;
}

.turbine-meta {
  display: flex;
  flex: 1 1 auto;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.turbine-meta span,
.map-status {
  color: #34413d;
  background: var(--accent-soft);
  border: 1px solid rgba(21, 122, 101, 0.18);
  border-radius: 999px;
  font-size: 12px;
  font-weight: 800;
}

.turbine-meta span {
  padding: 8px 10px;
}

.map-status {
  position: absolute;
  z-index: 500;
  right: 18px;
  bottom: 24px;
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 12px;
  background: rgba(255, 255, 255, 0.95);
  border-radius: var(--radius);
  box-shadow: var(--shadow);
}

@media (max-width: 880px) {
  .map-panel,
  .map-canvas {
    min-height: 68svh;
  }

  .map-topbar {
    flex-direction: column;
    align-items: stretch;
  }

  .turbine-select {
    flex: 0 1 auto;
    min-width: 0;
  }

  .turbine-meta {
    justify-content: flex-start;
  }
}

@media (max-width: 520px) {
  .map-topbar {
    top: 12px;
    right: 12px;
    left: 12px;
  }

  .map-status {
    right: 12px;
    bottom: 18px;
  }
}
</style>
