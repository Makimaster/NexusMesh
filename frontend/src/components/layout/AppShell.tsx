import { Outlet } from 'react-router';
import { Topbar } from './Topbar';
import { Sidebar } from './Sidebar';
import './layout.css';

export function AppShell() {
  return (
    <div className="mesh-app-shell">
      <Topbar />
      <div className="mesh-app-body">
        <Sidebar />
        <main className="mesh-app-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
