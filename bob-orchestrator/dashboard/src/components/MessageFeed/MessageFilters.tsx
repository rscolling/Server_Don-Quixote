import { useDashboard } from '../../context/DashboardContext';
import { agentLabel } from '../../api/types';

const AGENTS = ['', 'PM', 'RA', 'CE', 'QA', 'SE', 'RE', 'FE', 'BE', 'ORCH'];
const TYPES = ['', 'task_assignment', 'status_update', 'deliverable', 'feedback', 'question', 'escalation', 'state_change'];

export function MessageFilters() {
  const { state, dispatch } = useDashboard();
  const f = state.messageFilters;

  const set = (key: string, value: string) =>
    dispatch({ type: 'SET_MESSAGE_FILTER', key, value });

  return (
    <div style={{ display: 'flex', gap: '0.75rem', marginBottom: '0.75rem', flexWrap: 'wrap' }}>
      <select value={f.sender} onChange={e => set('sender', e.target.value)}>
        <option value="">All Senders</option>
        {AGENTS.filter(Boolean).map(a => (
          <option key={a} value={a}>{agentLabel(a)}</option>
        ))}
      </select>
      <select value={f.messageType} onChange={e => set('messageType', e.target.value)}>
        <option value="">All Types</option>
        {TYPES.filter(Boolean).map(t => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <input
        type="text"
        placeholder="Task ID..."
        value={f.taskId}
        onChange={e => set('taskId', e.target.value)}
        style={{ width: 100 }}
      />
    </div>
  );
}
