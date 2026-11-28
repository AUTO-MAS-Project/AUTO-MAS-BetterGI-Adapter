<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Domain, Editor, Option, Value } from './bridge'
import {
  AUTO_BOSS_CATALOG,
  BUILTIN_GROUP_SETTING_SECTIONS,
  type DragonSettingField,
  type DragonSettingSection,
  type WeeklyDomainTableRow,
} from './groupSettingsSchema'
import SettingInput from './SettingInput.vue'

const { editor, group, instance, strategies, domains } = defineProps<{
  editor: Editor
  group: string
  instance: string
  strategies: Option[]
  domains: Domain[]
}>()
const { get, post, t, disabled, revision, run, reloadContext } = editor
const endpoints = {
  dragon: 'one-dragon/settings',
  globalDomain: 'global-domain/settings',
  globalStygian: 'global-stygian/settings',
}
type Source = keyof typeof endpoints
type Settings = Record<string, Value>
const configName = 'MAS独立配置'
const guide = '根据提升指南选择秘境'
const sections = computed(() => BUILTIN_GROUP_SETTING_SECTIONS[group] ?? [])
const sources = computed<Source[]>(() => [
  ...new Set<Source>([
    'dragon',
    ...sections.value.flatMap(section => section.fields.map(field => field.source ?? 'dragon')),
  ]),
])
const data = ref<Partial<Record<Source, Settings>>>({})
const loading = ref(false)
const loadError = ref('')
let readVersion = 0

async function load() {
  if (!sections.value.length) return
  const version = ++readVersion
  const query = { configName, groupName: instance }
  loading.value = true
  loadError.value = ''
  try {
    const result = await Promise.all(
      sources.value.map(
        async source =>
          [source, (await get<{ data: Settings }>(endpoints[source], query)).data] as const
      )
    )
    if (version === readVersion) data.value = Object.fromEntries(result)
  } catch (cause) {
    if (version === readVersion) loadError.value = String(cause)
  } finally {
    if (version === readVersion) loading.value = false
  }
}
watch([() => instance, revision], () => void load(), { immediate: true })

function fieldValue(field: DragonSettingField) {
  const value = data.value[field.source ?? 'dragon']?.[field.key]
  if (
    field.type === 'select' &&
    value === '0' &&
    field.options?.some(option => option.value === '') &&
    !field.options.some(option => option.value === '0')
  )
    return ''
  return value
}

function locked(field: DragonSettingField) {
  if (!field.masterKey) return false
  const master = data.value[field.source ?? 'dragon']?.[field.masterKey] ?? ''
  return (master === field.masterValue) === !!field.masterInvert
}

function sectionEnabled(section: DragonSettingSection) {
  const field = section.enableField
  return !field || Boolean(fieldValue(field)) !== Boolean(field.invert)
}

const bossOptions = AUTO_BOSS_CATALOG.map(item => ({ value: item.name, label: item.label }))
function options(field: DragonSettingField) {
  if (field.type === 'strategy') return strategies
  if (field.type === 'boss') return bossOptions
  return field.options
}

const domainOptions = computed(() => [
  { value: guide, label: t('bettergiDomainPickerGuide') },
  ...domains.map(item => ({
    value: item.name,
    label: [item.name, item.region].filter(Boolean).join(' · '),
  })),
])
const weeklyField = (
  key: string,
  label: string,
  type: DragonSettingField['type']
): DragonSettingField => ({ key, label, type })
const domainValue = (row: WeeklyDomainTableRow) => data.value.dragon?.[row.domainKey]
const domainHit = (row: WeeklyDomainTableRow) =>
  domains.find(item => item.name === domainValue(row))
function rewards(row: WeeklyDomainTableRow) {
  const items = domainHit(row)?.rewards
  return [
    { value: '0', label: t('defaultValue') },
    ...(items?.length ? items : ['1', '2', '3']).map((label, index) => ({
      value: String(index + 1),
      label,
    })),
  ]
}

function write(field: DragonSettingField, value: Value, related: Settings = {}) {
  const source = field.source ?? 'dragon'
  const groupName = instance
  const fields = { [field.key]: value, ...related }
  void run(async () => {
    await post(endpoints[source], { configName, groupName, settings: fields })
    data.value[source] = { ...data.value[source], ...fields }
    await reloadContext()
  })
}
</script>

<template>
  <section class="subsection">
    <p v-if="!sections.length" class="hint">{{ t('bettergiGroupSettingsNone') }}</p>
    <p v-else-if="loading" role="status">{{ t('loading') }}</p>
    <div v-else-if="loadError">
      <p class="field-error">{{ loadError }}</p>
      <button type="button" @click="load">{{ t('reload') }}</button>
    </div>
    <fieldset v-else :disabled="disabled">
      <details v-for="section in sections" :key="section.title" class="card" open>
        <summary>{{ t(section.title) }}</summary>
        <SettingInput
          v-if="section.enableField"
          :editor="editor"
          :field="section.enableField"
          :value="fieldValue(section.enableField)"
          @change="write(section.enableField, $event)"
        />
        <div v-if="section.fields.length" class="grid">
          <template v-for="field in section.fields" :key="field.id || field.key">
            <SettingInput
              v-if="!field.hideWhenDisabled || !locked(field)"
              :editor="editor"
              :field="field"
              :value="fieldValue(field)"
              :options="options(field)"
              :disabled="locked(field) || !sectionEnabled(section)"
              @change="write(field, $event)"
            />
          </template>
        </div>
        <fieldset
          v-for="row in section.weeklyRows"
          :key="row.uid"
          :disabled="!sectionEnabled(section)"
          class="subsection"
        >
          <legend>{{ t(row.label) }}</legend>
          <div class="grid">
            <SettingInput
              :editor="editor"
              :field="weeklyField(row.partyKey, 'bettergiColParty', 'text')"
              :value="data.dragon?.[row.partyKey]"
              @change="write(weeklyField(row.partyKey, '', 'text'), $event)"
            />
            <SettingInput
              :editor="editor"
              :field="weeklyField(row.strategyKey, 'bettergiColStrategy', 'strategy')"
              :value="data.dragon?.[row.strategyKey]"
              :options="strategies"
              @change="write(weeklyField(row.strategyKey, '', 'strategy'), $event)"
            />
            <SettingInput
              :editor="editor"
              :field="weeklyField(row.domainKey, 'bettergiColDomain', 'select')"
              :value="domainValue(row)"
              :options="domainOptions"
              @change="
                write(weeklyField(row.domainKey, '', 'select'), $event, { [row.rewardKey]: '0' })
              "
            />
            <SettingInput
              :editor="editor"
              :field="weeklyField(row.rewardKey, 'bettergiColReward', 'select')"
              :value="data.dragon?.[row.rewardKey] || '0'"
              :options="rewards(row)"
              :disabled="
                !domainValue(row) ||
                domainValue(row) === guide ||
                domainHit(row)?.category === 'BlessDomain'
              "
              @change="write(weeklyField(row.rewardKey, '', 'select'), $event)"
            />
            <SettingInput
              v-if="row.runKey"
              :editor="editor"
              :field="weeklyField(row.runKey, 'bettergiColRun', 'bool')"
              :value="data.dragon?.[row.runKey] ?? true"
              @change="write(weeklyField(row.runKey, '', 'bool'), $event)"
            />
          </div>
        </fieldset>
        <fieldset
          v-for="row in section.weeklyFieldRows ??
          (section.dailyFieldRow ? [section.dailyFieldRow] : [])"
          :key="row.uid"
          :disabled="!sectionEnabled(section)"
          class="subsection"
        >
          <legend>{{ t(row.label) }}</legend>
          <div class="grid">
            <SettingInput
              v-for="field in row.fields"
              :key="field.key"
              :editor="editor"
              :field="field"
              :value="fieldValue(field)"
              :options="options(field)"
              @change="write(field, $event)"
            />
          </div>
        </fieldset>
      </details>
    </fieldset>
  </section>
</template>
