<script setup lang="ts">
import { computed, ref } from 'vue'
import type { Domain, Editor, Option, Value } from './bridge'
import {
  AUTO_BOSS_CATALOG,
  LEY_LINE_COUNTRY_OPTIONS,
  LEY_LINE_TYPE_OPTIONS,
} from './groupSettingsSchema'
import { move, parseList } from './queue'
import SettingInput from './SettingInput.vue'

type Scene = 'domain' | 'leyline' | 'boss'
type Condition = Record<string, string>
type Team = {
  name: string
  strategy: string
  note: string
  enabled: boolean
  scenes: Record<Scene, Condition[]>
}
const { editor, strategies, domains } = defineProps<{
  editor: Editor
  strategies: Option[]
  domains: Domain[]
}>()
const { config, disabled, t, run, save } = editor
const rows = computed(() => parseList<Team>(config.value.OneDragon.Teams))
const draft = ref<Team>()
const index = ref<number>()
const validation = ref('')
const scenes: { kind: Scene; label: string; add: string }[] = [
  { kind: 'domain', label: 'bettergiTeamSceneDomainTab', add: 'bettergiTeamSceneAddDomain' },
  { kind: 'leyline', label: 'bettergiTeamSceneLeylineTab', add: 'bettergiTeamSceneAddLeyline' },
  { kind: 'boss', label: 'bettergiTeamSceneBossTab', add: 'bettergiTeamSceneAddBoss' },
]
const options = (items: string[]) =>
  [...new Set(items)].filter(Boolean).map(value => ({ value, label: value }))
const bossRegions = options(AUTO_BOSS_CATALOG.map(item => item.region))
const domainRegions = computed(() => options(domains.map(item => item.region)))
const empty = (): Team => ({
  name: '',
  strategy: '',
  note: '',
  enabled: true,
  scenes: { domain: [], leyline: [], boss: [] },
})

function update(fields: Record<string, Value>) {
  void run(() => save('OneDragon', fields))
}
const persist = (rows: Team[]) => update({ Teams: JSON.stringify(rows) })
function edit(at?: number) {
  index.value = at
  validation.value = ''
  const row = at === undefined ? empty() : (JSON.parse(JSON.stringify(rows.value[at])) as Team)
  row.scenes = { ...empty().scenes, ...row.scenes }
  draft.value = row
}
function submit() {
  if (!draft.value) return
  const name = draft.value.name.trim()
  if (!name) {
    validation.value = t('bettergiTeamNameRequired')
    return
  }
  const editing = index.value
  if (rows.value.some((row, at) => at !== editing && row.name === name)) {
    validation.value = t('bettergiTeamNameExists')
    return
  }
  const scenes = draft.value.scenes
  const team = {
    ...draft.value,
    name,
    scenes: {
      domain: scenes.domain.filter(condition => condition.domain?.trim()),
      leyline: scenes.leyline.filter(
        condition => condition.country?.trim() && condition.type?.trim()
      ),
      boss: scenes.boss.filter(condition => condition.boss?.trim()),
    },
  }
  const next =
    editing === undefined
      ? [...rows.value, team]
      : rows.value.map((row, at) => (at === editing ? team : row))
  void run(async () => {
    await save('OneDragon', { Teams: JSON.stringify(next) })
    draft.value = undefined
  })
}
function toggle(at: number, enabled: boolean) {
  persist(rows.value.map((row, index) => (index === at ? { ...row, enabled } : row)))
}
function value(event: Event) {
  return (event.target as HTMLSelectElement).value
}
function changeRegion(condition: Condition, event: Event) {
  condition.region = value(event)
  delete condition.domain
  delete condition.reward
  delete condition.boss
}

function changeDomain(condition: Condition, domain: Value) {
  condition.domain = String(domain)
  delete condition.reward
}
</script>

<template>
  <fieldset class="card" :disabled="disabled">
    <h2>{{ t('bettergiTeamConfig') }}</h2>
    <div class="grid">
      <SettingInput
        :editor="editor"
        :field="{ key: 'PartyName', label: 'bettergiBattleParty', type: 'text' }"
        :value="config.OneDragon.PartyName"
        @change="update({ PartyName: $event })"
      />
      <SettingInput
        :editor="editor"
        :field="{ key: 'AutoBossStrategyName', label: 'bettergiBattleStrategy', type: 'strategy' }"
        :value="config.OneDragon.AutoBossStrategyName"
        :options="strategies"
        @change="update({ AutoBossStrategyName: $event })"
      />
    </div>
    <label class="switch-tile">
      <input
        type="checkbox"
        :checked="!!config.OneDragon.IfUseTeams"
        @change="update({ IfUseTeams: ($event.target as HTMLInputElement).checked })"
      />
      {{ t('bettergiTeamConfig') }}
    </label>
    <p class="hint">
      {{ t(config.OneDragon.IfUseTeams ? 'bettergiTeamGeneralHint' : 'bettergiTeamOffTip') }}
    </p>
    <fieldset :disabled="!config.OneDragon.IfUseTeams">
      <ol class="queue">
        <li v-for="(row, at) in rows" :key="at">
          <input
            type="checkbox"
            :checked="row.enabled !== false"
            :aria-label="row.name"
            @change="toggle(at, ($event.target as HTMLInputElement).checked)"
          />
          <button type="button" :aria-pressed="!!draft && index === at" @click="edit(at)">
            {{ row.name }}
          </button>
          <div class="row">
            <button
              type="button"
              :disabled="at === 0 || !!draft"
              :aria-label="t('up')"
              @click="persist(move(rows, at, at - 1))"
            >
              ↑
            </button>
            <button
              type="button"
              :disabled="at === rows.length - 1 || !!draft"
              :aria-label="t('down')"
              @click="persist(move(rows, at, at + 1))"
            >
              ↓
            </button>
            <button
              type="button"
              :disabled="!!draft"
              @click="persist([...rows.slice(0, at + 1), row, ...rows.slice(at + 1)])"
            >
              {{ t('duplicate') }}
            </button>
            <button
              type="button"
              :disabled="!!draft"
              @click="persist(rows.filter((_, index) => index !== at))"
            >
              {{ t('remove') }}
            </button>
          </div>
        </li>
      </ol>
      <button v-if="!draft" type="button" class="subsection" @click="edit()">
        {{ t('bettergiTeamAdd') }}
      </button>
      <div v-else class="subsection">
        <div class="grid">
          <label>{{ t('bettergiTeamNameColumn') }}<input v-model="draft.name" /></label>
          <label
            >{{ t('bettergiBattleStrategy') }}
            <select v-model="draft.strategy">
              <option value="">{{ t('defaultValue') }}</option>
              <option
                v-if="draft.strategy && !strategies.some(item => item.value === draft?.strategy)"
                :value="draft.strategy"
              >
                {{ draft.strategy }}
              </option>
              <option v-for="strategy in strategies" :key="strategy.value" :value="strategy.value">
                {{ strategy.label }}
              </option>
            </select>
          </label>
          <label>{{ t('bettergiTeamNoteColumn') }}<input v-model="draft.note" /></label>
        </div>
        <p class="hint">{{ t('bettergiTeamSceneDialogTip') }}</p>
        <details v-for="scene in scenes" :key="scene.kind" class="card" open>
          <summary>{{ t(scene.label) }}</summary>
          <div v-for="(condition, at) in draft.scenes[scene.kind]" :key="at" class="row">
            <template v-if="scene.kind === 'leyline'">
              <SettingInput
                :editor="editor"
                :field="{ key: 'country', label: 'bettergiTeamSceneCountry', type: 'select' }"
                :value="condition.country"
                :options="LEY_LINE_COUNTRY_OPTIONS"
                @change="condition.country = String($event)"
              />
              <SettingInput
                :editor="editor"
                :field="{ key: 'type', label: 'bettergiTeamSceneLeylineType', type: 'select' }"
                :value="condition.type"
                :options="LEY_LINE_TYPE_OPTIONS"
                @change="condition.type = String($event)"
              />
            </template>
            <template v-else>
              <label>
                {{ t('bettergiTeamSceneRegion') }}
                <select :value="condition.region ?? ''" @change="changeRegion(condition, $event)">
                  <option value="">{{ t('choose') }}</option>
                  <option
                    v-for="item in scene.kind === 'domain' ? domainRegions : bossRegions"
                    :key="item.value"
                    :value="item.value"
                  >
                    {{ t(item.label) }}
                  </option>
                  <option
                    v-if="
                      condition.region &&
                      !(scene.kind === 'domain' ? domainRegions : bossRegions).some(
                        item => item.value === condition.region
                      )
                    "
                    :value="condition.region"
                  >
                    {{ condition.region }}
                  </option>
                </select>
              </label>
              <template v-if="scene.kind === 'domain'">
                <SettingInput
                  :editor="editor"
                  :field="{ key: 'domain', label: 'bettergiTeamSceneDomain', type: 'select' }"
                  :value="condition.domain"
                  :options="
                    options(
                      domains
                        .filter(item => !condition.region || item.region === condition.region)
                        .map(item => item.name)
                    )
                  "
                  @change="changeDomain(condition, $event)"
                />
                <SettingInput
                  :editor="editor"
                  :field="{ key: 'reward', label: 'bettergiColReward', type: 'select' }"
                  :value="condition.reward"
                  :options="
                    options(domains.find(item => item.name === condition.domain)?.rewards ?? [])
                  "
                  @change="condition.reward = String($event)"
                />
              </template>
              <SettingInput
                v-else
                :editor="editor"
                :field="{ key: 'boss', label: 'bettergiTeamSceneBoss', type: 'select' }"
                :value="condition.boss"
                :options="
                  AUTO_BOSS_CATALOG.filter(
                    item => !condition.region || item.region === condition.region
                  ).map(item => ({ value: item.name, label: item.label }))
                "
                @change="condition.boss = String($event)"
              />
            </template>
            <button type="button" @click="draft.scenes[scene.kind].splice(at, 1)">
              {{ t('remove') }}
            </button>
          </div>
          <button type="button" @click="draft.scenes[scene.kind].push({})">
            {{ t(scene.add) }}
          </button>
        </details>
        <p v-if="validation" class="field-error">{{ validation }}</p>
        <div class="actions">
          <button type="button" @click="submit">{{ t('save') }}</button>
          <button type="button" @click="draft = undefined">{{ t('cancel') }}</button>
        </div>
      </div>
    </fieldset>
  </fieldset>
</template>
