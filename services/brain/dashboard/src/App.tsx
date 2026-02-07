import { ErrorBoundary } from "./components/ErrorBoundary";
import DashboardLayout from "./layout/DashboardLayout";
import { BrowserRouter } from "react-router-dom";

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <DashboardLayout />
      </BrowserRouter>
    </ErrorBoundary>
  );
}
