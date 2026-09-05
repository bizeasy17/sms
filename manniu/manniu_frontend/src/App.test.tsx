import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import App from './App'

test('renders the initial application screen', () => {
  render(<App />)

  expect(screen.getByRole('heading', { name: 'Get started' })).toBeTruthy()
})