<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import GameClient from './GameClient.vue'
import DragonQueue from './DragonQueue.vue'
import TeamSettings from './TeamSettings.vue'
import { usePanel, type Option, type Domain } from './bridge'

const editor = usePanel()
const { config, context, disabled, error, t, get, report, run, save } = editor
const ready = ref(false)
const strategies = ref<Option[]>([])
const nativeConfigs = ref<Option[]>([])
const domains = ref<Domain[]>([])
const assetErrors = ref<string[]>([])

async function loadOptions() {
  assetErrors.value = []
  if (!context.value?.rootConfigured) return
  const reads =
    context.value.base === 'native'
      ? [
          get<{ data: Option[] }>('one-dragon/configs').then(result => {
            nativeConfigs.value = result.data
          }),
        ]
      : [
          get<{ data: Option[] }>('strategies').then(result => {
            strategies.value = result.data
          }),
          get<{ data: Domain[] }>('domain-catalog').then(result => {
            domains.value = result.data
          }),
        ]
  for (const result of await Promise.allSettled(reads)) {
    if (result.status === 'rejected') assetErrors.value.push(String(result.reason))
  }
}

onMounted(async () => {
  try {
    await editor.initialize()
    ready.value = true
    await loadOptions()
  } catch (cause) {
    report(cause)
  }
})
watch([() => context.value?.base, () => context.value?.rootConfigured], () => {
  if (ready.value) void loadOptions()
})

function change(group: string, field: string, event: Event) {
  const value = (event.target as HTMLInputElement).value
  void run(() => save(group, { [field]: value }))
}
</script>

<template>
  <p id="status" role="status" :data-error="error ? '' : undefined">{{ error }}</p>
  <p v-if="!ready && !error" role="status">{{ t('loading') }}</p>
  <template v-if="ready && context">
    <GameClient :editor="editor" />
    <p v-if="!context.rootConfigured" class="hint">{{ t('pickScriptRootDirectory') }}</p>
    <p v-for="(message, index) in assetErrors" :key="index" class="field-error">{{ message }}</p>
    <button v-if="assetErrors.length" type="button" @click="loadOptions">{{ t('reload') }}</button>
    <fieldset v-if="context.base === 'native'" class="card" :disabled="disabled">
      <h2>{{ t('taskConfiguration') }}</h2>
      <p class="hint">{{ t('bettergiDirectModeAlert') }}</p>
      <label>
        {{ t('bettergiOneDragonName') }}
        <select
          :value="config.Task.OneDragonConfigName || '默认配置'"
          @change="change('Task', 'OneDragonConfigName', $event)"
        >
          <option :value="config.Task.OneDragonConfigName || '默认配置'">
            {{ config.Task.OneDragonConfigName || t('defaultValue') }}
          </option>
          <option
            v-for="item in nativeConfigs.filter(
              item => item.value !== (config.Task.OneDragonConfigName || '默认配置')
            )"
            :key="item.value"
            :value="item.value"
          >
            {{ item.label }}
          </option>
        </select>
      </label>
    </fieldset>
    <template v-else>
      <fieldset class="card" :disabled="disabled">
        <h2>{{ t('taskConfiguration') }}</h2>
        <label>
          {{ t('bettergiDailyRewardParty') }}
          <input
            :value="config.OneDragon.DailyRewardPartyName"
            @change="change('OneDragon', 'DailyRewardPartyName', $event)"
          />
        </label>
      </fieldset>
      <DragonQueue :editor="editor" :strategies="strategies" :domains="domains" />
      <TeamSettings :editor="editor" :strategies="strategies" :domains="domains" />
    </template>
  </template>
</template>
