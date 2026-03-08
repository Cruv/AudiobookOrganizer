import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import Layout from '@/components/Layout';
import ScanPage from '@/pages/ScanPage';
import ReviewPage from '@/pages/ReviewPage';
import OrganizePage from '@/pages/OrganizePage';
import PurgePage from '@/pages/PurgePage';
import SettingsPage from '@/pages/SettingsPage';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 10_000,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<ScanPage />} />
            <Route path="/review" element={<ReviewPage />} />
            <Route path="/organize" element={<OrganizePage />} />
            <Route path="/purge" element={<PurgePage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
