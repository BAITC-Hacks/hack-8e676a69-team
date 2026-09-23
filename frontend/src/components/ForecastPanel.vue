<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { Wind } from '@lucide/vue'
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
const horizonOptions = [0, 12, 24, 36, 48]

const forecastSeries = computed(() =>
  toForecastSeries(props.selectedTurbine.agentForecasts, props.t.agentNames).map((series) => ({
    ...series,
    selectedValue: valueAtHour(series.points, selectedHour.value),
  })),
)

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
    max: 48,
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
    min: 0.4,
    max: 0.9,
    interval: 0.1,
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
  selectedHour.value = Number(hour)

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

    <div class="chart-surface">
      <VChart
        ref="chartRef"
        class="forecast-echart"
        :option="chartOption"
        autoresize
        @click="handleChartClick"
      />
    </div>

    <div class="forecast-values" :aria-label="t.horizonValue">
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
</style>
