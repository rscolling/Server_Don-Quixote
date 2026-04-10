import { useState, useEffect } from 'react';
import { useDashboard } from '../../context/DashboardContext';
import { agentLabel } from '../../api/types';
import { apiFetch } from '../../api/client';

const AGENTS = ['', 'PM', 'RA', 'CE', 'QA', 'SE', 'RE', 'FE', 'BE'];
const PRIORITIES = ['', 'low', 'normal', 'high', 'critical'];

interface UserOption {
  user_email: string;
  user_name: string;
}

export function TaskFilters() {
  const { state, dispatch } = useDashboard();
  const f = state.taskFilters;
  const [users, setUsers] = useState<UserOption[]>([]);

  useEffect(() => {
    apiFetch<UserOption[]>('/sessions/users')
      .then(setUsers)
      .catch(() => {});
  }, []);

  const set = (key: string, value: string) =>
    dispatch({ type: 'SET_TASK_FILTER', key, value });

  return (
    <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
      <select value={f.assignee} onChange={e => set('assignee', e.target.value)}>
        <option value="">All Agents</option>
        {AGENTS.filter(Boolean).map(a => (
          <option key={a} value={a}>{agentLabel(a)}</option>
        ))}
      </select>
      <select value={f.priority} onChange={e => set('priority', e.target.value)}>
        <option value="">All Priorities</option>
        {PRIORITIES.filter(Boolean).map(p => (
          <option key={p} value={p}>{p.toUpperCase()}</option>
        ))}
      </select>
      {users.length > 0 && (
        <select value={f.user || ''} onChange={e => set('user', e.target.value)}>
          <option value="">All Users</option>
          {users.map(u => (
            <option key={u.user_email} value={u.user_email}>
              {u.user_name || u.user_email}
            </option>
          ))}
        </select>
      )}
      <input
        type="text"
        placeholder="Search tasks..."
        value={f.search}
        onChange={e => set('search', e.target.value)}
        style={{ minWidth: 200 }}
      />
    </div>
  );
}
