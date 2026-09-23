<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { BrainCircuit, Wind } from '@lucide/vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useRotatingAgentMessage } from '../composables/useRotatingAgentMessage'
import { formatPower, toForecastSeries, valueAtHour } from '../utils/forecastPlot'

use([
  CanvasRenderer,
  LineChart,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  ToolboxComponent,
  TooltipComponent,
])

const props = defineProps({
  forecastError: {
    type: String,
    default: '',
  },
  forecastStatus: {
    type: String,
    required: true,
  },
  predictionHours: {
    type: Number,
    default: 48,
  },
  rawForecast: {
    type: [Object, Array],
    default: null,
  },
  ticketId: {
    type: String,
    default: '',
  },
  selectedTurbine: {
    type: Object,
    required: true,
  },
  t: {
    type: Object,
    required: true,
  },
})

const chartRef = ref(null)
const selectedHour = ref(24)
const horizonOptions = computed(() =>
  [0, 12, 24, 36, 48].filter((hour) => hour <= props.predictionHours),
)

const forecastSeries = computed(() =>
  toForecastSeries(props.selectedTurbine.agentForecasts ?? [], props.t.agentNames).map((series) => ({
    ...series,
    selectedValue: valueAtHour(series.points, selectedHour.value),
  })),
)

const hasForecast = computed(() => forecastSeries.value.length > 0)
const isWorking = computed(() => ['submitting', 'preparing', 'pending'].includes(props.forecastStatus))
const rotatingAgentStatus = useRotatingAgentMessage(
  computed(() => props.forecastStatus),
  computed(() => props.t),
)
const statusMessage = computed(() => {
  if (rotatingAgentStatus.message.value) return rotatingAgentStatus.message.value
  if (props.forecastStatus === 'error') return props.forecastError
  if (props.forecastStatus === 'succeeded' && !hasForecast.value) return props.t.unsupportedForecastShape
  return props.t.waitingForForecast
})
const rawPreview = computed(() =>
  props.rawForecast ? JSON.stringify(props.rawForecast, null, 2).slice(0, 1600) : '',
)
const yAxisBounds = computed(() => {
  const values = forecastSeries.value.flatMap((series) => series.hourlyPoints.map((point) => point[1]))
  const min = Math.min(...values)
  const max = Math.max(...values)

  if (!Number.isFinite(min) || !Number.isFinite(max)) {
    return { min: 0, max: 1 }
  }

  const range = Math.max(max - min, 0.2)
  const padding = range * 0.16

  return {
    min: Number(Math.max(0, min - padding).toFixed(2)),
    max: Number((max + padding).toFixed(2)),
  }
})

const chartOption = computed(() => ({
  animationDuration: 650,
  animationDurationUpdate: 320,
  animationEasing: 'cubicOut',
  color: forecastSeries.value.map((series) => series.color),
  grid: {
    top: 62,
    right: 26,
    bottom: 76,
    left: 64,
  },
  legend: {
    top: 12,
    left: 12,
    itemWidth: 22,
    itemHeight: 9,
    itemGap: 24,
    icon: 'roundRect',
    textStyle: {
      color: '#46534e',
      fontSize: 12,
      fontWeight: 600,
    },
  },
  toolbox: {
    top: 4,
    right: 10,
    itemSize: 16,
    itemGap: 14,
    iconStyle: {
      borderColor: '#68736e',
    },
    emphasis: {
      iconStyle: {
        borderColor: '#157a65',
      },
    },
    feature: {
      dataZoom: {
        yAxisIndex: 'none',
        title: {
          zoom: props.t.chartZoom,
          back: props.t.chartZoomBack,
        },
      },
      restore: {
        title: props.t.chartReset,
      },
    },
  },
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: 'rgba(24, 33, 31, 0.96)',
    borderWidth: 0,
    padding: [10, 12],
    textStyle: {
      color: '#ffffff',
      fontSize: 12,
    },
    axisPointer: {
      type: 'line',
      snap: true,
      lineStyle: {
        color: '#157a65',
        type: 'dashed',
        width: 1.5,
      },
    },
    formatter(params) {
      const hour = params[0]?.value?.[0] ?? 0
      const values = params
        .map(
          (item) =>
            `<div class="chart-tooltip-row">${item.marker}<span>${item.seriesName}</span><strong>${formatPower(item.value[1])}</strong></div>`,
        )
        .join('')

      return `<div class="chart-tooltip-title">${hour}h</div>${values}`
    },
  },
  xAxis: {
    type: 'value',
    min: 0,
    max: props.predictionHours,
    interval: 6,
    name: props.t.forecastTimeAxis,
    nameLocation: 'middle',
    nameGap: 32,
    nameTextStyle: {
      color: '#68736e',
      fontSize: 11,
      fontWeight: 700,
    },
    axisLine: {
      lineStyle: { color: '#cbd5d0' },
    },
    axisTick: { show: false },
    axisLabel: {
      color: '#68736e',
      fontSize: 11,
      formatter: '{value}h',
    },
    splitLine: {
      lineStyle: {
        color: '#e5ebe8',
        type: 'dashed',
      },
    },
  },
  yAxis: {
    type: 'value',
    min: yAxisBounds.value.min,
    max: yAxisBounds.value.max,
    name: props.t.forecastPowerAxis,
    nameGap: 16,
    nameTextStyle: {
      color: '#68736e',
      fontSize: 11,
      fontWeight: 700,
      align: 'left',
    },
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: '#68736e',
      fontSize: 11,
      formatter: (value) => value.toFixed(1),
    },
    splitLine: {
      lineStyle: { color: '#e2e9e5' },
    },
  },
  dataZoom: [
    {
      type: 'inside',
      xAxisIndex: 0,
      filterMode: 'none',
      zoomOnMouseWheel: true,
      moveOnMouseWheel: true,
      moveOnMouseMove: true,
    },
    {
      type: 'slider',
      xAxisIndex: 0,
      filterMode: 'none',
      bottom: 8,
      height: 18,
      borderColor: 'transparent',
      backgroundColor: '#edf2ef',
      fillerColor: 'rgba(21, 122, 101, 0.16)',
      dataBackground: {
        lineStyle: { color: '#91a69d', opacity: 0.55 },
        areaStyle: { color: '#cbd9d3', opacity: 0.35 },
      },
      selectedDataBackground: {
        lineStyle: { color: '#157a65' },
        areaStyle: { color: '#8fc9ba', opacity: 0.45 },
      },
      handleStyle: {
        color: '#ffffff',
        borderColor: '#157a65',
      },
      moveHandleStyle: {
        color: '#157a65',
        opacity: 0.7,
      },
      textStyle: { color: '#68736e', fontSize: 10 },
    },
  ],
  series: forecastSeries.value.map((series, index) => ({
    id: series.id,
    name: series.name,
    type: 'line',
    data: series.hourlyPoints,
    smooth: 0.3,
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 7,
    lineStyle: {
      color: series.color,
      width: 3,
      shadowBlur: 8,
      shadowColor: `${series.color}33`,
      shadowOffsetY: 3,
    },
    itemStyle: {
      color: series.color,
      borderColor: '#ffffff',
      borderWidth: 2,
    },
    emphasis: {
      focus: 'series',
      lineStyle: { width: 4 },
    },
    markLine:
      index === 0
        ? {
            silent: true,
            symbol: 'none',
            lineStyle: {
              color: '#26342f',
              type: 'dashed',
              width: 1.5,
              opacity: 0.55,
            },
            label: {
              show: true,
              position: 'insideEndTop',
              formatter: `${selectedHour.value}h`,
              color: '#ffffff',
              backgroundColor: '#26342f',
              borderRadius: 4,
              padding: [4, 7],
              fontSize: 11,
              fontWeight: 700,
            },
            data: [{ xAxis: selectedHour.value }],
          }
        : undefined,
    markPoint: {
      silent: true,
      symbol: 'circle',
      symbolSize: 14,
      label: { show: false },
      itemStyle: {
        color: series.color,
        borderColor: '#ffffff',
        borderWidth: 3,
        shadowBlur: 8,
        shadowColor: `${series.color}66`,
      },
      data: [{ coord: [selectedHour.value, series.selectedValue] }],
    },
  })),
}))

function selectHour(hour) {
  selectedHour.value = Math.min(props.predictionHours, Math.max(0, Number(hour)))

  nextTick(() => {
    chartRef.value?.dispatchAction({
      type: 'showTip',
      seriesIndex: 0,
      dataIndex: selectedHour.value,
    })
  })
}

function handleChartClick(params) {
  const hour = params.value?.[0]

  if (Number.isFinite(hour)) {
    selectHour(hour)
  }
}

watch(
  () => props.selectedTurbine.id,
  () => selectHour(24),
)

watch(
  () => props.predictionHours,
  () => selectHour(selectedHour.value),
)
</script>

<template>
  <section class="forecast-panel">
    <div class="forecast-header">
      <div class="section-title">
        <Wind :size="18" />
        <span>{{ t.forecastTitle }}</span>
      </div>

      <div class="horizon-control">
        <span>{{ t.selectedHorizon }}</span>
        <div class="horizon-buttons" role="group" :aria-label="t.selectedHorizon">
          <button
            v-for="hour in horizonOptions"
            :key="hour"
            type="button"
            :class="{ active: selectedHour === hour }"
            @click="selectHour(hour)"
          >
            {{ hour }}h
          </button>
        </div>
        <label class="custom-hour">
          <input
            :value="selectedHour"
            type="number"
            min="0"
            max="48"
            step="1"
            :aria-label="t.horizonValue"
            @input="selectHour(Math.min(48, Math.max(0, Number($event.target.value))))"
          />
          <span>h</span>
        </label>
      </div>
    </div>

    <div v-if="forecastStatus !== 'succeeded' || !hasForecast" class="agent-status">
      <span class="thinking-icon" :class="{ active: isWorking }">
        <BrainCircuit :size="18" />
        <span v-if="isWorking" class="thinking-orbit"></span>
      </span>
      <div>
        <strong>{{ t.agentStatus }}</strong>
        <Transition name="status-message" mode="out-in">
          <small :key="statusMessage">{{ statusMessage }}</small>
        </Transition>
      </div>
      <code v-if="ticketId">{{ t.ticket }}: {{ ticketId }}</code>
    </div>

    <div class="chart-surface">
      <VChart
        v-if="hasForecast"
        ref="chartRef"
        class="forecast-echart"
        :option="chartOption"
        autoresize
        @click="handleChartClick"
      />
      <div v-else class="chart-empty">
        <span>{{ statusMessage }}</span>
      </div>
    </div>

    <details v-if="rawPreview && !hasForecast" class="raw-response">
      <summary>{{ t.rawResponse }}</summary>
      <pre>{{ rawPreview }}</pre>
    </details>

    <div v-if="hasForecast" class="forecast-values" :aria-label="t.horizonValue">
      <article
        v-for="series in forecastSeries"
        :key="series.id"
        class="forecast-value"
        :style="{ '--series-color': series.color }"
      >
        <span class="value-indicator"></span>
        <div>
          <span>{{ series.name }}</span>
          <strong>{{ formatPower(series.selectedValue) }}</strong>
        </div>
        <small>{{ selectedHour }}h</small>
      </article>
    </div>
  </section>
</template>

<style scoped>
.forecast-panel {
  display: grid;
  grid-column: 2;
  gap: 12px;
  padding: 16px 18px 18px;
  background: #f8faf9;
  border-top: 1px solid var(--line);
  box-shadow: 0 -14px 35px rgba(34, 47, 42, 0.08);
}

.agent-status {
  display: grid;
  grid-template-columns: 36px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: #ffffff;
  border: 1px solid #dce4e0;
  border-radius: var(--radius);
}

.thinking-icon {
  position: relative;
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  color: var(--accent);
  background: var(--accent-soft);
  border-radius: 8px;
}

.thinking-icon svg {
  position: relative;
  z-index: 1;
}

.thinking-icon.active svg {
  animation: think 1.4s ease-in-out infinite;
}

.thinking-orbit {
  position: absolute;
  inset: -4px;
  border: 1px solid rgba(21, 122, 101, 0.28);
  border-top-color: rgba(21, 122, 101, 0.95);
  border-radius: 10px;
  animation: orbitStatus 1.1s linear infinite;
}

.agent-status strong,
.agent-status small {
  display: block;
}

.agent-status strong {
  color: var(--text);
  font-size: 13px;
}

.agent-status small {
  margin-top: 2px;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.35;
  overflow-wrap: anywhere;
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

.agent-status code {
  max-width: 280px;
  overflow: hidden;
  padding: 7px 9px;
  color: #34413d;
  background: #eef3f0;
  border: 1px solid var(--line);
  border-radius: 7px;
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.forecast-header {
  display: flex;
  align-items: center;
  gap: 16px;
  justify-content: space-between;
}

.horizon-control {
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-size: 12px;
  font-weight: 800;
}

.horizon-buttons {
  display: inline-flex;
  gap: 3px;
  padding: 3px;
  background: #e9efec;
  border: 1px solid #dce5e0;
  border-radius: var(--radius);
}

.horizon-buttons button {
  min-width: 43px;
  min-height: 30px;
  padding: 0 10px;
  color: var(--muted);
  background: transparent;
  border: 0;
  border-radius: 5px;
  font-size: 12px;
  font-weight: 800;
  transition:
    color 0.18s ease,
    background 0.18s ease,
    box-shadow 0.18s ease;
}

.horizon-buttons button:hover {
  color: var(--text);
  background: rgba(255, 255, 255, 0.7);
}

.horizon-buttons button.active {
  color: #ffffff;
  background: var(--accent);
  box-shadow: 0 5px 14px rgba(21, 122, 101, 0.24);
}

.custom-hour {
  position: relative;
  display: flex;
  align-items: center;
}

.custom-hour input {
  width: 64px;
  min-height: 38px;
  padding: 7px 23px 7px 9px;
  background: #ffffff;
  font-size: 12px;
  font-weight: 800;
}

.custom-hour span {
  position: absolute;
  right: 9px;
  color: var(--muted);
  pointer-events: none;
}

.chart-surface {
  min-width: 0;
  height: 300px;
  overflow: hidden;
  background: #ffffff;
  border: 1px solid #dce4e0;
  border-radius: var(--radius);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.9),
    0 12px 30px rgba(34, 47, 42, 0.09);
}

.forecast-echart {
  width: 100%;
  height: 100%;
}

.chart-empty {
  display: grid;
  height: 100%;
  place-items: center;
  padding: 22px;
  color: var(--muted);
  font-size: 13px;
  font-weight: 800;
  text-align: center;
}

.raw-response {
  min-width: 0;
  background: #ffffff;
  border: 1px solid #dce4e0;
  border-radius: var(--radius);
}

.raw-response summary {
  padding: 9px 12px;
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.raw-response pre {
  max-height: 160px;
  margin: 0;
  overflow: auto;
  padding: 0 12px 12px;
  color: #34413d;
  font-size: 11px;
  line-height: 1.45;
}

.forecast-values {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.forecast-value {
  display: grid;
  grid-template-columns: 4px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 9px 11px;
  background: #ffffff;
  border: 1px solid #dce4e0;
  border-radius: 7px;
}

.value-indicator {
  width: 4px;
  height: 28px;
  background: var(--series-color);
  border-radius: 3px;
}

.forecast-value div {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  min-width: 0;
  gap: 12px;
}

.forecast-value div span {
  overflow: hidden;
  color: var(--muted);
  font-size: 12px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.forecast-value strong {
  color: var(--text);
  font-size: 17px;
  font-variant-numeric: tabular-nums;
}

.forecast-value small {
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
}

:deep(.chart-tooltip-title) {
  margin-bottom: 7px;
  font-size: 12px;
  font-weight: 800;
}

:deep(.chart-tooltip-row) {
  display: grid;
  grid-template-columns: 12px minmax(110px, 1fr) auto;
  align-items: center;
  gap: 7px;
  min-width: 210px;
  padding: 2px 0;
}

:deep(.chart-tooltip-row strong) {
  font-variant-numeric: tabular-nums;
}

@media (max-width: 880px) {
  .forecast-panel {
    grid-column: 1;
  }

  .forecast-header {
    align-items: flex-start;
    flex-direction: column;
  }
}

@media (max-width: 640px) {
  .agent-status {
    grid-template-columns: 36px minmax(0, 1fr);
  }

  .agent-status code {
    grid-column: 1 / -1;
    max-width: none;
  }

  .horizon-control {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .horizon-control > span {
    width: 100%;
  }

  .horizon-buttons {
    max-width: calc(100% - 74px);
    overflow-x: auto;
  }

  .chart-surface {
    height: 330px;
  }

  .forecast-values {
    grid-template-columns: 1fr;
  }
}

@keyframes think {
  0%,
  100% {
    transform: scale(0.94);
  }

  50% {
    transform: scale(1.08);
  }
}

@keyframes orbitStatus {
  to {
    transform: rotate(1turn);
  }
}
</style>
