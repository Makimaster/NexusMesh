import { Navigate, Route, Routes } from "react-router";

import { AppShell } from "./components/layout/AppShell";
import Dashboard from "./pages/Dashboard";
import Login from "./pages/Login";
import AgentsPage from "./pages/agents/AgentsPage";
import ExecutionDetailPage from "./pages/executions/ExecutionDetailPage";
import ExecutionsPage from "./pages/executions/ExecutionsPage";
import WorkflowsPage from "./pages/workflows/WorkflowsPage";

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/dashboard" element={<Dashboard />} />
      <Route element={<AppShell />}>
        <Route path="/agents" element={<AgentsPage />} />
        <Route path="/workflows" element={<WorkflowsPage />} />
        <Route path="/executions" element={<ExecutionsPage />} />
        <Route path="/executions/:id" element={<ExecutionDetailPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/agents" />} />
    </Routes>
  );
}
