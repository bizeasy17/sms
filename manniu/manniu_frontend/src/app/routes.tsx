import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import type { ReactNode } from 'react'
import { ApiLab } from '../ApiLab'
import { LoginPage } from '../features/auth/LoginPage'
import { StockPickerPage } from '../features/stock-picker/StockPickerPage'

export function AppRoutes({ researchPage }: { researchPage: ReactNode }) {
  return <BrowserRouter><Routes>
    <Route path="/" element={<RootRoute researchPage={researchPage} />} />
    <Route path="/stock-picker" element={<StockPickerPage />} />
    <Route path="/login" element={<LoginPage />} />
    <Route path="/public/api" element={<ApiLab />} />
    <Route path="*" element={<Navigate to="/" replace />} />
  </Routes></BrowserRouter>
}

function RootRoute({ researchPage }: { researchPage: ReactNode }) {
  const location = useLocation()
  const navigate = useNavigate()
  if (location.hash === '#universe') {
    navigate('/stock-picker', { replace: true })
    return null
  }
  return researchPage
}
