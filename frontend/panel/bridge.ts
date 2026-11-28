import { computed, ref, shallowRef } from 'vue'

export type Value = string | boolean | number | null | Value[] | { [key: string]: Value }
type Config = Record<string, Record<string, Value>>
type Change = { group: string; field: string; value: Value }
type Target = { kind: 'user'; scriptId: string; userId: string }
type State = { locale: string; i18nRevision: number; locked: boolean; busy: boolean }
type Snapshot = { config: Config }
type EditorContext = {
  base: 'native' | 'shared' | 'independent'
  rootConfigured: boolean
  gamePath: string
  plan: string
}
type Reply<T> = {
  ok: boolean
  status: number
  data: T & { code?: number; message?: string; detail?: string }
}

declare function connectPanel(): {
  getContext(): Promise<State & Snapshot & { target: Target }>
  translate(keys: string[]): Promise<{ locale: string; messages: Record<string, string> }>
  request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<Reply<T>>
  saveConfig(changes: Change[], phase: 'commit'): Promise<{ ok: boolean; message?: string }>
  onStateChange(callback: (state: State) => void): void
  onConfigReloaded(callback: (snapshot: Snapshot) => void): void
}

const locale = import.meta.glob('../../src/bettergi_adapter/i18n/zh-CN.json', {
  eager: true,
  import: 'default',
}) as Record<string, Record<string, string>>
const namespace = 'plugins.bettergi_adapter.'
const labels = Object.keys(Object.values(locale)[0]).flatMap(key =>
  key.startsWith(namespace + 'panel.') ? [key.slice(namespace.length)] : []
)

export class RequestError extends Error {
  constructor(
    public code: number,
    message: string
  ) {
    super(message)
  }
}

export function usePanel() {
  const panel = connectPanel()
  const config = shallowRef<Config>({})
  const state = shallowRef<State>()
  const target = shallowRef<Target>()
  const context = shallowRef<EditorContext>()
  const messages = shallowRef<Record<string, string>>({})
  const error = ref('')
  const saving = ref(false)
  const revision = ref(0)
  const disabled = computed(
    () => !state.value || state.value.locked || state.value.busy || saving.value
  )
  let translationVersion = 0
  let contextVersion = 0

  function t(key: string, params: Record<string, string> = {}) {
    return (
      messages.value['panel.editor.' + key] ??
      messages.value['panel.editor.setting.' + key] ??
      key
    ).replace(/\{(\w+)\}/g, (token, name: string) => params[name] ?? token)
  }

  function report(cause: unknown) {
    error.value = cause instanceof Error ? cause.message : String(cause)
  }

  async function applyState(next: State) {
    const previous = state.value
    state.value = next
    if (previous?.i18nRevision === next.i18nRevision && previous.locale === next.locale) return
    const version = ++translationVersion
    const responses = []
    for (let offset = 0; offset < labels.length; offset += 512) {
      responses.push(await panel.translate(labels.slice(offset, offset + 512)))
    }
    if (version === translationVersion) {
      document.documentElement.lang = next.locale
      messages.value = Object.assign({}, ...responses.map(result => result.messages))
    }
  }

  async function request<T>(method: 'GET' | 'POST', path: string, body?: unknown): Promise<T> {
    const { ok, status, data } = await panel.request<T>(method, path, body)
    if (!ok || (data?.code !== undefined && data.code !== 200)) {
      throw new RequestError(
        data?.code ?? status,
        data?.message || data?.detail || `HTTP ${status}`
      )
    }
    return data
  }

  function ids() {
    const { scriptId, userId } = target.value!
    return { scriptId, userId }
  }

  function editorPath(suffix = '') {
    const { scriptId, userId } = ids()
    return `/editor/user/${scriptId}/${userId}${suffix}`
  }

  function get<T>(path: string, query: Record<string, string> = {}) {
    return request<T>('GET', `/bettergi/${path}?${new URLSearchParams({ ...ids(), ...query })}`)
  }

  function post<T>(path: string, fields: object) {
    return request<T>('POST', `/bettergi/${path}`, { ...ids(), ...fields })
  }

  async function reloadContext() {
    const version = ++contextVersion
    const result = await request<EditorContext>('GET', editorPath())
    if (version === contextVersion) context.value = result
  }

  async function initialize() {
    const snapshot = await panel.getContext()
    target.value = snapshot.target
    config.value = snapshot.config
    panel.onStateChange(next => void applyState(next).catch(report))
    panel.onConfigReloaded(next => {
      config.value = next.config
      revision.value++
      void reloadContext().catch(report)
    })
    await Promise.all([applyState(snapshot), reloadContext()])
  }

  async function run(operation: () => Promise<void>) {
    if (saving.value) return
    error.value = ''
    saving.value = true
    try {
      await operation()
    } catch (cause) {
      report(cause)
    } finally {
      saving.value = false
    }
  }

  async function save(group: string, fields: Record<string, Value>) {
    const changes = Object.entries(fields).map(([field, value]) => ({ group, field, value }))
    const result = await panel.saveConfig(changes, 'commit')
    if (!result.ok) throw new Error(result.message)
    config.value = { ...config.value, [group]: { ...config.value[group], ...fields } }
  }

  return {
    config,
    context,
    revision,
    state,
    disabled,
    error,
    t,
    report,
    initialize,
    request,
    editorPath,
    ids,
    get,
    post,
    reloadContext,
    run,
    save,
  }
}

export type Editor = ReturnType<typeof usePanel>
export type Option = { label: string; value: string }
export type Domain = { name: string; region: string; category: string; rewards: string[] }
