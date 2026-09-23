import { computed, onBeforeUnmount, ref, watch } from 'vue'

const ACTIVE_STATUSES = new Set(['submitting', 'preparing', 'pending'])

export function useRotatingAgentMessage(status, messages) {
  const messageIndex = ref(0)
  let intervalId

  const activeMessages = computed(() => {
    const value = messages.value

    if (status.value === 'submitting') return [value.creatingTicket]
    if (status.value === 'preparing') return value.agentWorkMessages?.preparing ?? [value.preparingData]
    if (status.value === 'pending') return value.agentWorkMessages?.pending ?? [value.aiAgentsThinking]

    return []
  })

  const isRotating = computed(() => ACTIVE_STATUSES.has(status.value))
  const message = computed(() => {
    if (!isRotating.value) return ''

    const options = activeMessages.value.filter(Boolean)
    return options[messageIndex.value % Math.max(options.length, 1)] ?? ''
  })

  function stopRotation() {
    window.clearInterval(intervalId)
    intervalId = undefined
  }

  function startRotation() {
    stopRotation()
    messageIndex.value = 0

    if (!isRotating.value || activeMessages.value.length < 2) return

    intervalId = window.setInterval(() => {
      messageIndex.value += 1
    }, 2400)
  }

  watch([isRotating, activeMessages], startRotation, { immediate: true })
  onBeforeUnmount(stopRotation)

  return {
    isRotating,
    message,
  }
}
