<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RequestError, type Editor, type Option, type Value } from './bridge'
import { move, type Entry, type Kind } from './queue'
import SettingInput from './SettingInput.vue'
import type { DragonSettingField } from './groupSettingsSchema'

type Project = {
  name: string
  folderName?: string
  status?: string
  jsScriptSettingsObject?: Record<string, Value>
} & Record<string, Value | undefined>
type Group = { projects?: Project[] } & Record<string, unknown>
type Source = { kind: Kind; label: string; options: Option[] }
type LayoutItem = {
  type?: string
  name?: string
  label?: string
  default?: Value
  options?: Array<
    string | { label?: string; name?: string; text?: string; key?: string; value?: string }
  >
}
const { editor, row, name, catalogs } = defineProps<{
  editor: Editor
  row: Entry
  name: string
  catalogs: Source[]
}>()
const { t, get, post, run, disabled, revision, report } = editor
const group = ref<Group>()
const loadError = ref('')
const kind = ref<Kind>('js')
const pick = ref('')
const index = ref<number>()
const items = ref<LayoutItem[]>([])
const readme = ref('')
const values = ref<Record<string, Value>>({})
const projects = computed(() => group.value?.projects ?? [])
const sources = computed(() =>
  catalogs.filter(source => ['js', 'pathing', 'keymouse'].includes(source.kind))
)
let readVersion = 0
let editVersion = 0

function makeProject(kind: Kind, value: string): Project {
  const parts = value.split('/')
  const file = parts.pop()
  const label = catalogs
    .find(source => source.kind === kind)
    ?.options.find(item => item.value === value)?.label
  return {
    type: kind === 'js' ? 'Javascript' : kind === 'keymouse' ? 'KeyMouse' : 'Pathing',
    name: kind === 'pathing' ? file + '.json' : (label ?? value),
    folderName: kind === 'pathing' ? parts.join('/') : value,
    status: 'Enabled',
    schedule: 'Daily',
    runNum: 1,
  }
}

async function load() {
  const version = ++readVersion
  group.value = undefined
  loadError.value = ''
  index.value = undefined
  editVersion++
  try {
    const result = await get<{ data: Group }>('script-group/detail', { name })
    if (version === readVersion) group.value = result.data
  } catch (cause) {
    if (version !== readVersion) return
    if (cause instanceof RequestError && cause.code === 404 && row.kind !== 'scriptgroup') {
      group.value = {
        projects: ['js', 'pathing', 'keymouse'].includes(row.kind)
          ? [makeProject(row.kind, row.name)]
          : [],
      }
    } else {
      loadError.value = String(cause)
    }
  }
}
watch(
  () => name,
  () => void load(),
  { immediate: true }
)
watch(revision, () => {
  if (index.value === undefined) void load()
})

async function persist(next: Project[]) {
  const updated = {
    ...group.value,
    projects: next.map((item, index) => ({ ...item, index: index + 1 })),
  }
  await post('script-group/save', { name, data: updated })
  group.value = updated
  index.value = undefined
  editVersion++
}

async function edit(at: number) {
  const version = ++editVersion
  const project = projects.value[at]
  index.value = at
  items.value = []
  readme.value = ''
  values.value = { ...project.jsScriptSettingsObject }
  if (project.type !== 'Javascript' || !project.folderName) return
  try {
    const query = { folder: project.folderName }
    const [layout, documentation] = await Promise.all([
      get<{ data: LayoutItem[] }>('script-settings-ui', query),
      get<{ data: string }>('script-readme', query),
    ])
    if (version !== editVersion) return
    items.value = layout.data
    readme.value = documentation.data
  } catch (cause) {
    if (version === editVersion) report(cause)
  }
}

function choices(item: LayoutItem): Option[] {
  return (item.options ?? []).map(option => {
    if (typeof option === 'string') return { value: option, label: option }
    const label = option.label ?? option.name ?? option.text ?? option.value ?? ''
    return { label, value: option.value ?? option.key ?? option.name ?? label }
  })
}

function field(item: LayoutItem): DragonSettingField {
  const kind = item.type?.toLowerCase() ?? ''
  let type: DragonSettingField['type'] = 'text'
  if (
    ['multi-checkbox', 'multicheckbox', 'multi_select', 'multi-select', 'multiselect'].includes(
      kind
    ) ||
    Array.isArray(item.default)
  )
    type = 'multi'
  else if (
    ['checkbox', 'switch', 'bool', 'boolean', 'toggle'].includes(kind) ||
    typeof item.default === 'boolean'
  )
    type = 'bool'
  else if (
    item.options?.length ||
    ['select', 'dropdown', 'combo', 'combobox', 'radio'].includes(kind)
  )
    type = 'select'
  return {
    key: item.name ?? '',
    label: item.label ?? item.name ?? '',
    type,
    options: choices(item),
  }
}

function fieldValue(item: LayoutItem) {
  const value = values.value[item.name!] ?? item.default
  return field(item).type === 'bool' && typeof value === 'string'
    ? !['', 'false', '0', '否', 'no', 'off'].includes(value.trim().toLowerCase())
    : value
}

function submit() {
  const at = index.value
  if (at === undefined) return
  void run(() =>
    persist(
      projects.value.map((item, i) =>
        i === at ? { ...item, jsScriptSettingsObject: values.value } : item
      )
    )
  )
}
</script>

<template>
  <section class="subsection">
    <h3>{{ t('bettergiProjectConfigTab') }}</h3>
    <template v-if="loadError">
      <p class="field-error">{{ loadError }}</p>
      <button type="button" @click="load">{{ t('reload') }}</button>
    </template>
    <p v-else-if="!group" role="status">{{ t('loading') }}</p>
    <fieldset v-else :disabled="disabled">
      <div class="row">
        <label>
          {{ t('source') }}
          <select v-model="kind" @change="pick = ''">
            <option v-for="source in sources" :key="source.kind" :value="source.kind">
              {{ t(source.label) }}
            </option>
          </select>
        </label>
        <label>
          {{ t('project') }}
          <select v-model="pick">
            <option value="">{{ t('choose') }}</option>
            <option
              v-for="item in sources.find(source => source.kind === kind)?.options"
              :key="item.value"
              :value="item.value"
            >
              {{ item.label }}
            </option>
          </select>
        </label>
        <button
          type="button"
          :disabled="!pick"
          @click="run(() => persist([...projects, makeProject(kind, pick)]))"
        >
          {{ t('add') }}
        </button>
      </div>
      <p v-if="!projects.length" class="hint">{{ t('bettergiProjectEmpty') }}</p>
      <ol class="queue">
        <li v-for="(project, at) in projects" :key="at">
          <input
            type="checkbox"
            :checked="project.status !== 'Disabled'"
            :aria-label="project.name"
            @change="
              run(() =>
                persist(
                  projects.map((item, i) =>
                    i === at
                      ? {
                          ...item,
                          status: ($event.target as HTMLInputElement).checked
                            ? 'Enabled'
                            : 'Disabled',
                        }
                      : item
                  )
                )
              )
            "
          />
          <button type="button" :aria-pressed="index === at" @click="edit(at)">
            {{ project.name }}
          </button>
          <div class="row">
            <button
              type="button"
              :disabled="at === 0"
              :aria-label="t('up')"
              @click="run(() => persist(move(projects, at, at - 1)))"
            >
              ↑
            </button>
            <button
              type="button"
              :disabled="at === projects.length - 1"
              :aria-label="t('down')"
              @click="run(() => persist(move(projects, at, at + 1)))"
            >
              ↓
            </button>
            <button type="button" @click="run(() => persist(projects.filter((_, i) => i !== at)))">
              {{ t('remove') }}
            </button>
          </div>
        </li>
      </ol>
      <div v-if="index !== undefined" class="subsection">
        <h4>{{ projects[index]?.name }}</h4>
        <template v-for="(item, at) in items" :key="item.name ?? at">
          <h4 v-if="['separator', 'section', 'divider'].includes(item.type ?? '')">
            {{ item.label }}
          </h4>
          <SettingInput
            v-else-if="item.name"
            :editor="editor"
            :field="field(item)"
            :value="fieldValue(item)"
            @change="values[item.name] = $event"
          />
        </template>
        <p v-if="!items.length" class="hint">{{ t('bettergiProjectNoSettingsFile') }}</p>
        <details v-if="readme">
          <summary>{{ t('bettergiProjectReadmeTab') }}</summary>
          <pre>{{ readme }}</pre>
        </details>
        <div class="actions">
          <button v-if="items.length" type="button" @click="submit">{{ t('save') }}</button>
          <button type="button" @click="index = undefined">{{ t('cancel') }}</button>
        </div>
      </div>
    </fieldset>
  </section>
</template>
