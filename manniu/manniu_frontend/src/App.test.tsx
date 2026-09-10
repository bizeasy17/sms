import { render, screen } from '@testing-library/react'
import { beforeEach, expect, test, vi } from 'vitest'
import App from './App'

beforeEach(() => {
  window.localStorage.clear()
  vi.restoreAllMocks()
})

test('requires the existing login session', () => {
  window.history.replaceState({}, '', '/')
  render(<App />)

  expect(screen.getByRole('heading', { name: '登录后查看接口目录' })).toBeTruthy()
  expect(screen.getByRole('link', { name: '前往登录' }).getAttribute('href')).toBe('/login')
})

test('renders the login page at the login route', () => {
  window.history.replaceState({}, '', '/login')
  render(<App />)

  expect(screen.getByRole('heading', { name: '登录 API Lab' })).toBeTruthy()
  expect(screen.getByLabelText('用户名')).toBeTruthy()
  expect(screen.getByLabelText('密码')).toBeTruthy()
})
