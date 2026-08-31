import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach } from 'vitest'
import { cleanup } from '@testing-library/react'
import { setLang } from '../i18n'

// The app defaults to English (t() starts in 'en'); tests are written against
// the zh dictionary, so pin the language before every test.
beforeEach(() => {
  setLang('zh')
})

afterEach(() => {
  cleanup()
  setLang('zh')
})
