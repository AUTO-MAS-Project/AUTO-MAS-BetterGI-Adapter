<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Domain, Editor, Option, Value } from './bridge'
import {
  builtins,
  combat,
  move,
  parseList,
  planSteps,
  stepName,
  type Entry,
  type Group,
  type Kind,
} from './queue'
import GroupSettings from './GroupSettings.vue'
import GroupProjects from './GroupProjects.vue'

const { editor, strategies, domains } = defineProps<{
  editor: Editor
  strategies: Option[]
  domains: Domain[]
}>()
const { config, context, t, get, request, disabled, save, run, reloadContext } = editor
type Catalog = { label: string; kind: Kind; options: Option[] }
type Tree = { name: string; files: string[]; dirs: Tree[] }
const slots = ref<Catalog[]>([])
const categories = [
  { kind: 'builtin', label: 'builtin', options: [] },
  { kind: 'custom', label: 'bettergiGroupKindCustom', options: [] },
  { kind: 'scriptgroup', label: 'bettergiGroupKindScriptGroup', options: [] },
  { kind: 'js', label: 'bettergiGroupKindJs', options: [] },
  { kind: 'pathing', label: 'bettergiGroupKindPathing', options: [] },
  { kind: 'keymouse', label: 'bettergiGroupKindKeyMouse', options: [] },
] satisfies Catalog[]
const catalogs = computed<Catalog[]>(() =>
  categories.map(category => ({
    ...category,
    options:
      category.kind === 'builtin'
        ? Object.entries(builtins).map(([value, key]) => ({ value, label: t(key) }))
        : (slots.value.find(item => item.kind === category.kind)?.options ?? []),
  }))
)
const loading = ref(false)
const catalogError = ref('')
const pickedKind = ref<Kind>('builtin')
const pickedName = ref('')
const search = ref('')
const confirmingClear = ref(false)
const candidates = computed(() => {
  const query = search.value.trim().toLowerCase()
  return (
    catalogs.value
      .find(category => category.kind === pickedKind.value)
      ?.options.filter(option => option.label.toLowerCase().includes(query)) ?? []
  )
})
const selectedId = ref<number>()
const dragging = ref<number>()
const oneDragon = computed(() => config.value.OneDragon)
const custom = computed(() => parseList<Group>(oneDragon.value.CustomGroups))
const groups = computed(() => parseList<string>(oneDragon.value.Groups))
const steps = computed(() => planSteps(context.value?.plan ?? ''))
const selected = computed(() => rows.value.find(row => row.uid === selectedId.value))
const rows = computed<Entry[]>(() => {
  const stored = parseList<Entry>(oneDragon.value.Queue)
  const primary =
    stored.length || !groups.value.length
      ? stored
      : Object.keys(builtins).map(name => ({ name, kind: 'builtin' as const }) as Entry)
  const variants = primary.filter(row => row.name !== '__mas_stamina_combat__')
  let next = Math.max(0, ...variants.map(row => row.uid ?? 0))
  const queue = variants.map(row => {
    const kind = Object.hasOwn(builtins, row.name)
      ? 'builtin'
      : row.kind && row.kind !== 'builtin' && row.kind !== 'custom'
        ? row.kind
        : sourceKind(row.name)
    return { ...row, kind, uid: row.uid ?? ++next }
  })
  if (oneDragon.value.IfUseCustomGroups) {
    for (const row of custom.value) {
      if (!queue.some(item => item.name === row.name)) {
        queue.push({ ...row, kind: sourceKind(row.name), uid: ++next })
      }
    }
  }
  return queue
})

function sourceKind(name: string): Kind {
  return (
    slots.value.find(
      category =>
        category.kind !== 'custom' && category.options.some(option => option.value === name)
    )?.kind ?? 'custom'
  )
}

function flatten(nodes: Tree[], parent = ''): Option[] {
  return nodes.flatMap(node => {
    const prefix = `${parent}${node.name}/`
    return [
      ...node.files.map(file => ({
        value: prefix + file.replace(/\.json$/i, ''),
        label: prefix + file,
      })),
      ...flatten(node.dirs, prefix),
    ]
  })
}

async function loadCatalogs() {
  if (!context.value?.rootConfigured || loading.value) return
  loading.value = true
  catalogError.value = ''
  const options = (path: string) => get<{ data: Option[] }>(path).then(result => result.data)
  const results = await Promise.allSettled([
    get<{ data: Group[] }>('one-dragon/custom-groups', {
      configName: 'MAS独立配置',
      useMasConfig: 'true',
    }).then(result => result.data.map(row => ({ value: row.name, label: row.name }))),
    options('script-groups'),
    options('js-scripts'),
    get<{ dirs: Tree[] }>('auto-pathing-tree').then(result => flatten(result.dirs)),
    options('key-mouse-scripts'),
  ])
  slots.value = categories.slice(1).flatMap((category, index) => {
    const result = results[index]
    if (result.status === 'fulfilled') return [{ ...category, options: result.value }]
    catalogError.value = String(result.reason)
    return slots.value.filter(item => item.kind === category.kind)
  })
  loading.value = false
}

watch([() => context.value?.rootConfigured, editor.revision], () => void loadCatalogs(), {
  immediate: true,
})

function label(row: Entry) {
  const base =
    row.displayName ||
    catalogs.value
      .find(item => item.kind === row.kind)
      ?.options.find(item => item.value === row.name)?.label ||
    row.name
  return row.suffix ? `${base} · ${row.suffix}` : base
}

function enabled(row: Entry) {
  if (row.kind !== 'builtin')
    return row.enabled ?? custom.value.find(item => item.name === row.name)?.enabled ?? true
  if (!groups.value.includes(row.name)) return false
  if (!combat.has(row.name)) return true
  return (
    steps.value.find(step => step.name === stepName(row, rows.value, steps.value))?.enabled !==
    false
  )
}

function isCustom(row: Entry) {
  return row.kind === 'custom' || row.kind === 'js' || row.kind === 'scriptgroup'
}

function setCustomGroups(enabled: boolean) {
  void run(async () => {
    const next =
      custom.value.length || !enabled
        ? custom.value
        : (
            await get<{ data: Group[] }>('one-dragon/custom-groups', {
              configName: 'MAS独立配置',
              useMasConfig: 'true',
            })
          ).data
    await save('OneDragon', { IfUseCustomGroups: enabled, CustomGroups: JSON.stringify(next) })
  })
}

async function persist(next: Entry[], fields: Record<string, Value> = {}) {
  await reloadContext()
  const batch = next.map(row => {
    const name = stepName(row, rows.value, steps.value)
    if (row.kind === 'builtin') {
      return { ...row, step: undefined, planUid: steps.value.find(step => step.name === name)?.uid }
    }
    return {
      ...row,
      step: name === row.name ? undefined : name,
      enabled: row.enabled ?? enabled(row),
    }
  })
  await save('OneDragon', {
    Queue: JSON.stringify(batch),
    ...(next.some(row => row.kind === 'builtin' && combat.has(row.name))
      ? { UseExecutionLayer: true }
      : {}),
    ...fields,
  })
  await reloadContext()
}

function toggle(row: Entry, checked: boolean) {
  void run(async () => {
    if (row.kind === 'builtin') {
      const group = row.name
      if (combat.has(group)) {
        const query = new URLSearchParams({
          ...editor.ids(),
          name: stepName(row, rows.value, steps.value),
          enabled: String(checked),
        })
        await request('POST', '/bettergi/one-dragon/plan/step-enabled?' + query)
        await persist(rows.value, { Groups: [...new Set([...groups.value, group])] })
      } else {
        const next = checked
          ? [...new Set([...groups.value, group])]
          : groups.value.filter(name => name !== group)
        await persist(rows.value, { Groups: next })
      }
    } else {
      await persist(
        rows.value.map(item => (item.uid === row.uid ? { ...item, enabled: checked } : item))
      )
    }
  })
}

function add(kind: Kind, name: string, alias?: Entry) {
  if (!name) return
  return run(async () => {
    const row: Entry = { kind, name, uid: Math.max(0, ...rows.value.map(item => item.uid)) + 1 }
    if (alias) {
      row.displayName = alias.displayName
      row.suffix = alias.suffix
    }
    const fields: Record<string, Value> = {}
    if (kind === 'builtin') fields.Groups = [...new Set([...groups.value, name])]
    if (isCustom(row)) {
      fields.IfUseCustomGroups = true
      fields.CustomGroups = JSON.stringify([
        ...custom.value.filter(item => item.name !== name),
        { name, enabled: true },
      ])
    }
    await persist([...rows.value, row], fields)
    selectedId.value = row.uid
  })
}

function remove(row: Entry) {
  void run(async () => {
    const next = rows.value.filter(item => item.uid !== row.uid)
    const fields: Record<string, Value> = {}
    if (!next.some(item => item.name === row.name)) {
      if (row.kind === 'builtin') fields.Groups = groups.value.filter(name => name !== row.name)
      if (isCustom(row))
        fields.CustomGroups = JSON.stringify(custom.value.filter(item => item.name !== row.name))
    }
    await persist(next, fields)
    if (selectedId.value === row.uid) selectedId.value = undefined
  })
}

function clear() {
  void run(async () => {
    await persist([], { Groups: [], CustomGroups: '[]' })
    selectedId.value = undefined
    confirmingClear.value = false
  })
}

function reorder(from: number, to: number) {
  if (disabled.value || from === to) return
  void run(() => persist(move(rows.value, from, to)))
}

function startDrag(index: number, event: DragEvent) {
  dragging.value = index
  event.dataTransfer?.setData('text/plain', String(index))
}

function resetSearch() {
  pickedName.value = ''
  search.value = ''
}

function rename(row: Entry, field: 'displayName' | 'suffix', event: Event) {
  const value = (event.target as HTMLInputElement).value.trim()
  void run(() =>
    persist(rows.value.map(item => (item.uid === row.uid ? { ...item, [field]: value } : item)))
  )
}
</script>

<template>
  <section class="card">
    <h2>{{ t('queue') }}</h2>
    <fieldset :disabled="disabled">
      <div class="row">
        <label>
          {{ t('source') }}
          <select v-model="pickedKind" @change="resetSearch">
            <option v-for="entry in catalogs" :key="entry.kind" :value="entry.kind">
              {{ t(entry.label) }}
            </option>
          </select>
        </label>
        <label>
          {{ t('search') }}
          <input v-model="search" type="search" @input="pickedName = ''" />
        </label>
        <label>
          {{ t('bettergiEnterGroupName') }}
          <select v-model="pickedName">
            <option value="">{{ t('choose') }}</option>
            <option v-for="item in candidates" :key="item.value" :value="item.value">
              {{ item.label }}
            </option>
          </select>
        </label>
        <button type="button" :disabled="!pickedName" @click="add(pickedKind, pickedName)">
          {{ t('add') }}
        </button>
        <button type="button" :disabled="loading || !context?.rootConfigured" @click="loadCatalogs">
          {{ t('reload') }}
        </button>
      </div>
      <label class="switch-tile">
        <input
          type="checkbox"
          :checked="!!oneDragon.IfUseCustomGroups"
          :disabled="!context?.rootConfigured"
          @change="setCustomGroups(($event.target as HTMLInputElement).checked)"
        />
        {{ t('manageCustomGroups') }}
      </label>
      <p v-if="catalogError" class="field-error">{{ catalogError }}</p>
      <p v-if="!rows.length" class="hint">{{ t('emptyQueue') }}</p>
      <ol class="queue">
        <li
          v-for="(row, index) in rows"
          :key="row.uid"
          @dragover.prevent
          @drop.prevent="dragging !== undefined && reorder(dragging, index)"
        >
          <input
            type="checkbox"
            :aria-label="label(row)"
            :checked="enabled(row)"
            @change="toggle(row, ($event.target as HTMLInputElement).checked)"
          />
          <button
            type="button"
            :aria-pressed="selectedId === row.uid"
            @click="selectedId = row.uid"
          >
            {{ label(row) }}
          </button>
          <div class="row">
            <button
              type="button"
              class="drag-handle"
              :draggable="!disabled"
              :title="t('move')"
              @dragstart="startDrag(index, $event)"
              @dragend="dragging = undefined"
              :aria-label="t('move')"
            >
              ↕
            </button>
            <button
              type="button"
              :disabled="index === 0"
              :aria-label="t('up')"
              @click="reorder(index, index - 1)"
            >
              ↑
            </button>
            <button
              type="button"
              :disabled="index === rows.length - 1"
              :aria-label="t('down')"
              @click="reorder(index, index + 1)"
            >
              ↓
            </button>
          </div>
        </li>
      </ol>
      <div v-if="rows.length" class="actions">
        <template v-if="confirmingClear">
          <span>{{ t('confirmClearQueue') }}</span>
          <button type="button" @click="clear">{{ t('confirm') }}</button>
          <button type="button" @click="confirmingClear = false">{{ t('cancel') }}</button>
        </template>
        <button v-else type="button" @click="confirmingClear = true">{{ t('clearQueue') }}</button>
      </div>
      <div v-if="selected" class="subsection">
        <h3>{{ label(selected) }}</h3>
        <div class="row">
          <label v-if="selected.kind !== 'builtin'">
            {{ t('bettergiRenameNameLabel') }}
            <input
              :value="selected.displayName"
              @change="rename(selected, 'displayName', $event)"
            />
          </label>
          <label>
            {{ t('bettergiRenameSuffixLabel') }}
            <input :value="selected.suffix" @change="rename(selected, 'suffix', $event)" />
          </label>
        </div>
        <div class="actions">
          <button type="button" @click="add(selected.kind, selected.name, selected)">
            {{ t('duplicate') }}
          </button>
          <button type="button" @click="remove(selected)">{{ t('remove') }}</button>
        </div>
      </div>
    </fieldset>
    <template v-if="selected && context?.rootConfigured">
      <GroupSettings
        v-if="selected.kind === 'builtin'"
        :key="selected.uid"
        :editor="editor"
        :group="selected.name"
        :instance="stepName(selected, rows, steps)"
        :strategies="strategies"
        :domains="domains"
      />
      <GroupProjects
        v-else
        :key="selected.uid"
        :editor="editor"
        :row="selected"
        :name="stepName(selected, rows, steps)"
        :catalogs="catalogs"
      />
    </template>
  </section>
</template>
