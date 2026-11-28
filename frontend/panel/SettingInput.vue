<script setup lang="ts">
import { computed } from 'vue'
import type { Editor, Option, Value } from './bridge'
import type { DragonSettingField } from './groupSettingsSchema'

const { field, editor, value, options } = defineProps<{
  field: DragonSettingField
  editor: Editor
  value?: Value
  options?: Option[]
  disabled?: boolean
}>()
const emit = defineEmits<{ change: [value: Value] }>()
const { t } = editor

const selected = computed(() => (value == null ? '' : String(value)))
const choices = computed(() => options ?? field.options ?? [])
const multi = computed({
  get: () =>
    Array.isArray(value)
      ? value.map(String)
      : typeof value === 'string' && value
        ? value.split(/[,;，；、｜|]/).map(item => item.trim())
        : [],
  set: (values: string[]) => emit('change', values),
})

function change(event: Event) {
  const input = event.target as HTMLInputElement
  if (field.type === 'number') {
    if (input.reportValidity() && input.value !== '') emit('change', input.valueAsNumber)
  } else {
    emit('change', input.value)
  }
}
</script>

<template>
  <label :class="{ 'switch-tile': field.type === 'bool' }">
    <input
      v-if="field.type === 'bool'"
      type="checkbox"
      :disabled="disabled"
      :checked="field.invert ? !value : !!value"
      @change="emit('change', ($event.target as HTMLInputElement).checked !== !!field.invert)"
    />
    <span>{{ t(field.label) }}</span>
    <select v-if="field.type === 'multi'" v-model="multi" multiple :disabled="disabled">
      <option v-for="item in choices" :key="item.value" :value="item.value">
        {{ t(item.label) }}
      </option>
      <option
        v-for="item in multi.filter(value => !choices.some(option => option.value === value))"
        :key="item"
        :value="item"
      >
        {{ item }}
      </option>
    </select>
    <select
      v-else-if="['select', 'strategy', 'boss'].includes(field.type)"
      :value="selected"
      :disabled="disabled"
      @change="change"
    >
      <option v-if="!choices.some(item => item.value === '')" value="">
        {{ t('defaultValue') }}
      </option>
      <option v-if="selected && !choices.some(item => item.value === selected)" :value="selected">
        {{ selected }}
      </option>
      <option v-for="item in choices" :key="item.value" :value="item.value">
        {{ t(item.label) }}
      </option>
    </select>
    <input
      v-else-if="field.type !== 'bool'"
      :value="value"
      :disabled="disabled"
      :type="field.type"
      :min="field.min"
      :max="field.max"
      :step="field.step"
      @change="change"
    />
    <small v-if="field.help" class="hint">{{ t(field.help) }}</small>
  </label>
</template>
