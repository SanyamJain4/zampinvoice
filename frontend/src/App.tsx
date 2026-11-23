import { Route, Routes } from 'react-router-dom'
import { Layout } from '@/components/Layout'
import Dashboard from '@/pages/Dashboard'
import ProcessInvoice from '@/pages/ProcessInvoice'
import Invoices from '@/pages/Invoices'
import InvoiceDetail from '@/pages/InvoiceDetail'
import ReviewQueue from '@/pages/ReviewQueue'
import PurchaseOrders from '@/pages/PurchaseOrders'
import Vendors from '@/pages/Vendors'
import HistoryPage from '@/pages/History'
import Audit from '@/pages/Audit'
import SettingsPage from '@/pages/Settings'
import { EmptyState } from '@/components/ui'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Dashboard />} />
        <Route path="process" element={<ProcessInvoice />} />
        <Route path="invoices" element={<Invoices />} />
        <Route path="invoices/:id" element={<InvoiceDetail />} />
        <Route path="reviews" element={<ReviewQueue />} />
        <Route path="purchase-orders" element={<PurchaseOrders />} />
        <Route path="vendors" element={<Vendors />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="audit" element={<Audit />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<EmptyState title="Page not found" hint="Use the sidebar to get back on track." />} />
      </Route>
    </Routes>
  )
}
