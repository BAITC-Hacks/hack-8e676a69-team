const WIND_FARM_ID = 'wpp-main'

const SERIES_COLORS = ['#157a65', '#2877c8', '#d5961f', '#7a4fc4', '#d15b3a']
const VALUE_KEYS = [
  'value',
  'prediction',
  'forecast',
  'power',
  'normalized_power',
  'active_power',
  'power_mw',
  'y',
]

function formatCoord(latitude, longitude) {
  return `${Number(latitude).toFixed(6)}, ${Number(longitude).toFixed(6)}`
}

function toDateInputValue(value) {
  if (!value) return ''
  return String(value).slice(0, 10)
}

function localizedText(en, ru, kk) {
  return { en, ru, kk }
}

function turbineLabel(turbine) {
  const suffix = turbine.dataset_number ?? turbine.id
  return {
    en: turbine.name ?? `Turbine ${suffix}`,
    ru: `Турбина ${suffix}`,
    kk: `${suffix}-турбина`,
  }
}

export function normalizeBootstrap(payload) {
  const turbines = (payload?.turbines ?? []).map((turbine) => ({
    id: turbine.id,
    backendId: turbine.id,
    windFarmId: WIND_FARM_ID,
    coords: [Number(turbine.latitude), Number(turbine.longitude)],
    coordLabel: formatCoord(turbine.latitude, turbine.longitude),
    datasetStart: turbine.dataset_start,
    datasetEnd: turbine.dataset_end,
    defaultHorizonStart: turbine.default_horizon_start,
    timezone: turbine.timezone ?? payload.timezone,
    agentForecasts: [],
    name: turbineLabel(turbine),
  }))

  const center = turbines.length
    ? [
        turbines.reduce((sum, turbine) => sum + turbine.coords[0], 0) / turbines.length,
        turbines.reduce((sum, turbine) => sum + turbine.coords[1], 0) / turbines.length,
      ]
    : [43.644174, 78.537216]

  const windFarm = {
    id: WIND_FARM_ID,
    coords: center,
    coordLabel: formatCoord(center[0], center[1]),
    testPeriod: datasetPeriod(turbines),
    horizon: `${payload?.prediction_hours ?? 48} h`,
    name: localizedText('Wind Power Plant', 'ВЭС', 'Жел электр станциясы'),
    region: localizedText('Almaty Region', 'Алматинская область', 'Алматы облысы'),
  }

  return {
    predictionHours: payload?.prediction_hours ?? 48,
    pollIntervalMs: payload?.poll_interval_ms ?? 1000,
    timezone: payload?.timezone ?? turbines[0]?.timezone ?? 'Asia/Almaty',
    limits: payload?.limits ?? {},
    defaults: {
      turbine_id: payload?.defaults?.turbine_id ?? turbines[0]?.backendId,
      horizon_start: toDateInputValue(payload?.defaults?.horizon_start ?? turbines[0]?.defaultHorizonStart),
      history_days: payload?.defaults?.history_days ?? 30,
    },
    windFarms: [windFarm],
    turbines,
  }
}

function datasetPeriod(turbines) {
  const starts = turbines.map((turbine) => turbine.datasetStart).filter(Boolean).sort()
  const ends = turbines.map((turbine) => turbine.datasetEnd).filter(Boolean).sort()

  if (!starts.length || !ends.length) return ''

  return `${toDateInputValue(starts[0])} - ${toDateInputValue(ends.at(-1))}`
}

export function applyForecastToTurbines(turbines, turbineId, agentForecasts) {
  return turbines.map((turbine) =>
    turbine.backendId === turbineId || turbine.id === turbineId
      ? { ...turbine, agentForecasts }
      : turbine,
  )
}

export function normalizeForecastResponse(payload, labels) {
  if (!payload || typeof payload !== 'object') return []

  if (Array.isArray(payload)) {
    return normalizeSeriesCollection(payload, labels)
  }

  if (payload.error) {
    throw new Error(payload.error.message ?? payload.error.code ?? 'Worker returned an error')
  }

  const candidates = [
    payload.agents,
    payload.series,
    payload.forecasts,
    payload.predictions,
    payload.data,
    payload.result,
  ]

  for (const candidate of candidates) {
    const series = normalizeSeriesCollection(candidate, labels)
    if (series.length) return series
  }

  return []
}

function normalizeSeriesCollection(candidate, labels) {
  if (Array.isArray(candidate)) {
    if (candidate.every((item) => typeof item === 'number')) {
      return [toSeries({ id: 'model-agent', nameKey: 'model', values: candidate }, 1, labels)]
    }

    const series = candidate
      .map((item, index) => toSeries(item, index, labels))
      .filter((item) => item.points.length)

    if (series.length) return series

    const points = normalizePoints(candidate)
    return points.length ? [toSeries({ id: 'model-agent', nameKey: 'model', points }, 1, labels)] : []
  }

  if (candidate && typeof candidate === 'object') {
    return Object.entries(candidate)
      .map(([key, value], index) =>
        toSeries({ id: key, name: readableName(key), nameKey: key, points: value, values: value }, index, labels),
      )
      .filter((item) => item.points.length)
  }

  return []
}

function toSeries(source, index, labels) {
  const id = String(source?.id ?? source?.agent_id ?? source?.nameKey ?? `agent-${index + 1}`)
  const nameKey = source?.nameKey ?? source?.type ?? id
  const points = normalizePoints(source?.points ?? source?.forecast ?? source?.predictions ?? source?.values ?? source?.data ?? source)

  return {
    id,
    nameKey,
    name: source?.name ?? labels?.[nameKey] ?? readableName(nameKey),
    color: source?.color ?? SERIES_COLORS[index % SERIES_COLORS.length],
    points,
  }
}

function normalizePoints(value) {
  if (!Array.isArray(value)) return []

  const firstTimestamp = value.find((point) => typeof point === 'object' && point?.timestamp)?.timestamp
  const firstTime = firstTimestamp ? Date.parse(firstTimestamp) : null

  return value
    .map((point, index) => normalizePoint(point, index, firstTime))
    .filter((point) => Number.isFinite(point.hour) && Number.isFinite(point.value))
    .sort((a, b) => a.hour - b.hour)
}

function normalizePoint(point, index, firstTime) {
  if (typeof point === 'number') {
    return { hour: index, value: point }
  }

  if (Array.isArray(point)) {
    return { hour: Number(point[0]), value: Number(point[1]) }
  }

  if (!point || typeof point !== 'object') {
    return { hour: Number.NaN, value: Number.NaN }
  }

  const valueKey = VALUE_KEYS.find((key) => Number.isFinite(Number(point[key])))
  const hour =
    point.hour ??
    point.horizon ??
    point.horizon_hour ??
    point.t ??
    point.x ??
    timestampToHour(point.timestamp ?? point.time, firstTime) ??
    index

  return {
    hour: Number(hour),
    value: Number(point[valueKey]),
  }
}

function timestampToHour(timestamp, firstTime) {
  if (!timestamp || !firstTime) return null

  const time = Date.parse(timestamp)
  if (!Number.isFinite(time)) return null

  return Math.round((time - firstTime) / 3_600_000)
}

function readableName(value) {
  return String(value)
    .replace(/[-_]+/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

export { toDateInputValue }
