export function formatPower(value) {
  return value.toFixed(2)
}

export function valueAtHour(points, hour) {
  const exactPoint = points.find((point) => point.hour === hour)

  if (exactPoint) {
    return exactPoint.value
  }

  const previousPoint = [...points].reverse().find((point) => point.hour < hour) ?? points[0]
  const nextPoint = points.find((point) => point.hour > hour) ?? points.at(-1)

  if (previousPoint.hour === nextPoint.hour) {
    return previousPoint.value
  }

  const ratio = (hour - previousPoint.hour) / (nextPoint.hour - previousPoint.hour)
  return previousPoint.value + (nextPoint.value - previousPoint.value) * ratio
}

export function toForecastSeries(agentForecasts, agentNames) {
  return agentForecasts.map((agent) => ({
    ...agent,
    name: agentNames[agent.nameKey] ?? agent.name ?? agent.id,
    hourlyPoints: Array.from({ length: 49 }, (_, hour) => [hour, valueAtHour(agent.points, hour)]),
    lastValue: agent.points.at(-1).value,
  }))
}
