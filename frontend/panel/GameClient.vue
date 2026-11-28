<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import type { Editor } from './bridge'

const { editor } = defineProps<{ editor: Editor }>()
const { config, context, revision, t, get, run, save, request, editorPath, report, disabled } =
  editor
const servers = {
  官服: 'bettergiServerCn',
  B服: 'bettergiServerBili',
  亚服: 'bettergiServerAsia',
  欧服: 'bettergiServerEurope',
  美服: 'bettergiServerAmerica',
  港澳台服: 'bettergiServerTwHkMo',
}
type GameInfo = { installPath: string | null; channel: keyof typeof servers | '国际服' | null }
type Update = {
  status: 'pending' | 'running' | 'success' | 'error' | 'cancelled'
  detail: string
  log: string
}
const info = ref<GameInfo>()
const gameError = ref('')
const confirmation = ref(false)
const taskId = ref('')
const snapshot = ref<Update>()
const running = computed(() => !!taskId.value)
const bili = computed(() => (info.value?.channel ?? config.value.Switch.Resource) === 'B服')
const mismatch = computed(() => {
  const channel = info.value?.channel
  const resource = config.value.Switch.Resource
  return channel && channel !== (resource === '官服' || resource === 'B服' ? resource : '国际服')
})
const channel = computed(() => {
  const value = info.value?.channel
  return value === '国际服' ? 'bettergiChannelGlobal' : value ? servers[value] : ''
})
let timer: ReturnType<typeof setTimeout>
let lastProgress = 0
let active = true
onScopeDispose(() => {
  active = false
  clearTimeout(timer)
})

watch(
  [() => context.value?.gamePath, () => context.value?.rootConfigured, revision],
  async ([gamePath, rootConfigured], _, cleanup) => {
    let valid = true
    cleanup(() => {
      valid = false
    })
    if (!rootConfigured) return
    gameError.value = ''
    try {
      const result = await get<GameInfo>('game-info', { detectPath: gamePath ?? '' })
      if (valid) info.value = result
    } catch (cause) {
      if (valid) gameError.value = String(cause)
    }
  },
  { immediate: true }
)

async function poll() {
  if (!active || !taskId.value) return
  gameError.value = ''
  try {
    const result = await request<Update>('GET', editorPath('/update/' + taskId.value))
    if (!taskId.value || !active) return
    if (result.log !== snapshot.value?.log) lastProgress = Date.now()
    snapshot.value = result
    if (result.status !== 'pending' && result.status !== 'running') {
      taskId.value = ''
      return
    }
    if (Date.now() - lastProgress > 300_000) {
      await stop()
      gameError.value = t('bettergiUpdateTimed')
      return
    }
    timer = setTimeout(poll, 1500)
  } catch (cause) {
    if (!active) return
    gameError.value = String(cause)
  }
}

function start() {
  confirmation.value = false
  void run(async () => {
    gameError.value = ''
    snapshot.value = undefined
    const result = await request<{ taskId: string }>('POST', editorPath('/update'))
    taskId.value = result.taskId
    lastProgress = Date.now()
    void poll()
  })
}

async function stop() {
  clearTimeout(timer)
  const result = await request<Update>('POST', editorPath('/update/' + taskId.value + '/stop'))
  taskId.value = ''
  snapshot.value = result
}

function change(field: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  void run(() => save('Switch', { [field]: value }))
}
</script>

<template>
  <section class="card">
    <h2>{{ t('bettergiGameClient') }}</h2>
    <fieldset :disabled="disabled" class="grid">
      <label>
        {{ t('bettergiGameServer') }}
        <select :value="config.Switch.Resource" @change="change('Resource', $event)">
          <option v-for="(label, id) in servers" :key="id" :value="id">{{ t(label) }}</option>
        </select>
      </label>
      <label>
        {{ t('bettergiAccountUid') }}
        <input :value="config.Switch.Uid" @change="change('Uid', $event)" />
      </label>
    </fieldset>
    <p class="hint">
      {{ info?.installPath || context?.gamePath || t('bettergiGameClientPlaceholder') }}
    </p>
    <p v-if="channel" class="hint">{{ t(channel) }}</p>
    <p v-if="mismatch" class="field-error">{{ t('serverMismatch') }}</p>
    <p v-if="gameError" class="field-error">{{ gameError }}</p>
    <div class="actions">
      <template v-if="confirmation">
        <span>{{ t('bettergiWillBeUpdated') }}</span>
        <button type="button" :disabled="disabled" @click="start">{{ t('confirm') }}</button>
        <button type="button" @click="confirmation = false">{{ t('cancel') }}</button>
      </template>
      <button v-else-if="running" type="button" @click="stop().catch(report)">
        {{ t('stop') }}
      </button>
      <button
        v-else
        type="button"
        :disabled="disabled || bili || !context?.rootConfigured"
        :title="bili ? t('bettergiUpdateUnsupportedHint') : undefined"
        @click="confirmation = true"
      >
        {{ t('checkUpdates') }}
      </button>
      <button v-if="running && gameError" type="button" @click="poll">{{ t('reload') }}</button>
    </div>
    <pre v-if="running || snapshot" role="status">{{
      snapshot?.log || snapshot?.detail || t('bettergiUpdateConnecting')
    }}</pre>
    <p v-if="snapshot && !running" :class="{ 'field-error': snapshot.status === 'error' }">
      {{ t(snapshot.status) }} {{ snapshot.detail }}
    </p>
  </section>
</template>
