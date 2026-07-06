import { NavLink } from 'react-router';

const NAV_ITEMS = [
  { to: '/agents', label: 'Agents' },
  { to: '/workflows', label: 'Workflows' },
  { to: '/executions', label: 'Executions' },
] as const;

export function Sidebar() {
  return (
    <nav className="mesh-sidebar">
      <ul className="mesh-sidebar-nav">
        {NAV_ITEMS.map(({ to, label }) => (
          <li key={to}>
            <NavLink
              to={to}
              className={({ isActive }) =>
                isActive ? 'mesh-sidebar-link mesh-sidebar-link--active' : 'mesh-sidebar-link'
              }
            >
              {label}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
