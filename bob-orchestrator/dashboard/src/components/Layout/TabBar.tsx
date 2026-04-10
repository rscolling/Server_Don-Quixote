import { useDashboard } from '../../context/DashboardContext';

const TABS = ['Task Board', 'Agents', 'Messages', 'Cost', 'Users', 'Ideas'];

export function TabBar() {
  const { state, dispatch } = useDashboard();

  return (
    <nav style={{
      display: 'flex',
      gap: 0,
      background: 'var(--bg-surface)',
      borderBottom: '1px solid var(--border)',
      paddingLeft: '1.5rem',
    }}>
      {TABS.map((tab, i) => (
        <button
          key={tab}
          onClick={() => dispatch({ type: 'SET_TAB', tab: i })}
          style={{
            padding: '0.6rem 1.2rem',
            fontSize: '0.85rem',
            fontWeight: state.activeTab === i ? 600 : 400,
            color: state.activeTab === i ? 'var(--accent)' : 'var(--text-secondary)',
            borderBottom: state.activeTab === i ? '2px solid var(--accent)' : '2px solid transparent',
            transition: 'all 0.15s',
          }}
        >
          {tab}
        </button>
      ))}
    </nav>
  );
}
