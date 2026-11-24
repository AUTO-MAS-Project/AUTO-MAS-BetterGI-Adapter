import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import assert from 'node:assert/strict'
import { test } from 'node:test'

const bridgeSource = readFileSync(
  new URL('../src/bettergi_adapter/resources/MASOneDragon/main.js', import.meta.url),
  'utf8'
)

for (const legacyValue of [false, true]) {
  test(`旧计划中的冒险之证开关为 ${legacyValue} 时仍执行地脉花`, async () => {
    // 新版 BGI 的公开任务参数不再提供 useAdventurerHandbook。
    class LeyLineParam {
      isResinExhaustionMode = false
      openModeCountMin = false
      team = ''
      friendshipTeam = ''

      constructor(count, country, leyLineOutcropType) {
        Object.assign(this, { count, country, leyLineOutcropType })
        Object.seal(this)
      }
    }

    const calls = []
    const messages = []
    await runInNewContext(`'use strict';\n${bridgeSource}`, {
      AutoLeyLineOutcropParam: LeyLineParam,
      dispatcher: { runAutoLeyLineOutcropTask: async param => { calls.push(param) } },
      genshin: { returnMainUi: async () => {} },
      log: { info: line => messages.push(line) },
      settings: {
        plan: JSON.stringify({
          version: 1,
          steps: [
            {
              uid: 'leyline',
              name: '自动地脉花',
              enabled: true,
              settings: {
                count: 3,
                country: '蒙德',
                leyLineOutcropType: '启示之花',
                useAdventurerHandbook: legacyValue,
              },
            },
          ],
        }),
      },
    })

    assert.deepEqual(messages.filter(line => line.startsWith('MAS_STEP_FAIL:')), [])
    assert.ok(messages.includes('MAS_STEP_DONE: leyline 自动地脉花'))
    assert.equal(calls.length, 1)
    const [param] = calls
    assert.deepEqual([param.count, param.country, param.leyLineOutcropType], [3, '蒙德', '启示之花'])
    assert.equal('useAdventurerHandbook' in param, false)
    assert.equal(messages.at(-1), 'MAS_PLAN_DONE')
  })
}

test('关闭每周秘境后只使用每日秘境、队伍、策略和奖励', async () => {
  class DomainParam {
    setCombatStrategyPath(name) { return name }
  }
  const calls = []
  const messages = []
  await runInNewContext(bridgeSource, {
    AutoDomainParam: DomainParam,
    dispatcher: { runAutoDomainTask: async param => { calls.push(param) } },
    genshin: { returnMainUi: async () => {} },
    log: { info: line => messages.push(line) },
    settings: {
      plan: JSON.stringify({ version: 1, steps: [{
        uid: 'domain', name: '自动秘境', enabled: true,
        settings: {
          weeklyDomainEnabled: false, domainName: 'daily', partyName: 'today',
          combatStrategyPath: 'daily-strategy', sundaySelectedValue: '0',
          weeklyDomain: { default: { domainName: 'weekly', partyName: 'old', strategy: 'old', reward: '2' } },
        },
      }] }),
    },
  })
  assert.ok(messages.includes('MAS_STEP_DONE: domain 自动秘境'), messages.join('\n'))
  assert.equal(calls.length, 1)
  const [param] = calls
  assert.deepEqual(
    [param.domainName, param.partyName, param.combatStrategyPath, param.sundaySelectedValue],
    ['daily', 'today', 'daily-strategy', '0'],
  )
})
