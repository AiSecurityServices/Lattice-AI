import { afterEach, describe, expect, it } from 'vitest'
import { getLang, setLang, t } from './i18n'

afterEach(() => setLang('zh'))

describe('i18n', () => {
  it('defaults to Chinese', () => {
    expect(getLang()).toBe('zh')
    expect(t('page.title')).toBe('设置')
  })

  it('switches to English and back', () => {
    setLang('en')
    expect(getLang()).toBe('en')
    expect(document.documentElement.lang).toBe('en')
    expect(t('page.title')).toBe('Settings')
    expect(t('llm.custom')).toBe('Other (custom)')
    expect(t('composer.pause')).toBe('Pause')
    setLang('zh')
    expect(t('page.title')).toBe('设置')
    expect(document.documentElement.lang).toBe('zh')
  })

  it('falls back to the key for missing translations', () => {
    setLang('en')
    expect(t('missing.key')).toBe('missing.key')
  })
})
