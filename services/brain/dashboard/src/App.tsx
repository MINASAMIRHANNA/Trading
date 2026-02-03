import { ErrorBoundary } from "./components/ErrorBoundary";
import DashboardLayout from "./layout/DashboardLayout";

export default function App() {
  return (
    <ErrorBoundary>
      <DashboardLayout />
    </ErrorBoundary>
  );
}
