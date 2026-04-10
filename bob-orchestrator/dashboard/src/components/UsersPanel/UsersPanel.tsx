import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../../api/client';
import { useDashboard } from '../../context/DashboardContext';
import { StatusDot } from '../common/StatusDot';
import { Badge } from '../common/Badge';
import { timeAgo } from '../common/TimeAgo';
import { agentLabel, agentColor, PRIORITY_COLORS } from '../../api/types';
import type { Task } from '../../api/types';

interface UserProfile {
  user_email: string;
  user_name: string;
  user_role: string;
  last_seen: string;
  total_messages: number;
  session_count: number;
  is_online: number;
  last_latitude: number | null;
  last_longitude: number | null;
  last_endpoint: string;
}

interface Session {
  session_id: string;
  user_email: string;
  user_name: string;
  user_role: string;
  endpoint: string;
  client_ip: string;
  latitude: number | null;
  longitude: number | null;
  connected_at: string;
  last_activity_at: string;
  disconnected_at: string | null;
  message_count: number;
  is_active: number;
}

function isIpAddress(s: string): boolean {
  return /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(s);
}

function displayName(user: UserProfile): string {
  // Prefer user_name if it's not an IP
  if (user.user_name && !isIpAddress(user.user_name)) return user.user_name;
  // Fall back to email if it's not an IP
  if (user.user_email && !isIpAddress(user.user_email)) return user.user_email;
  // Last resort: show as "Guest (IP)"
  return `Guest (${user.user_email})`;
}

const ROLE_COLORS: Record<string, string> = {
  rob: '#4ecca3',
  member: '#60a5fa',
  guest: '#6b7280',
  unknown: '#6b7280',
};

export function UsersPanel() {
  const { state } = useDashboard();
  const [users, setUsers] = useState<UserProfile[]>([]);
  const [selectedUser, setSelectedUser] = useState<string | null>(null);
  const [userSessions, setUserSessions] = useState<Session[]>([]);
  const [error, setError] = useState('');

  const fetchUsers = useCallback(async () => {
    try {
      const data = await apiFetch<UserProfile[]>('/sessions/users');
      setUsers(data);
      setError('');
    } catch (e: any) {
      setError(e.message);
    }
  }, []);

  useEffect(() => {
    fetchUsers();
    const interval = setInterval(fetchUsers, 10000);
    return () => clearInterval(interval);
  }, [fetchUsers]);

  const selectUser = async (email: string) => {
    setSelectedUser(email);
    try {
      const sessions = await apiFetch<Session[]>(`/sessions/user/${encodeURIComponent(email)}`);
      setUserSessions(sessions);
    } catch { setUserSessions([]); }
  };

  // Filter tasks for selected user
  const userTasks = selectedUser
    ? state.tasks.filter(t => {
        // Match by email in cost tracker user field, or by IP
        return t.metadata?.user === selectedUser
          || t.watchers?.includes(selectedUser);
      })
    : [];


  if (error) {
    return <div style={{ color: 'var(--error)', padding: '2rem' }}>Error: {error}</div>;
  }

  return (
    <div style={{ display: 'flex', gap: '1.5rem', height: 'calc(100vh - 180px)' }}>
      {/* User list */}
      <div style={{ width: 320, flexShrink: 0, overflowY: 'auto' }}>
        <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.75rem' }}>
          Users ({users.length})
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {users.map(u => (
            <div
              key={u.user_email}
              onClick={() => selectUser(u.user_email)}
              style={{
                padding: '0.75rem',
                background: selectedUser === u.user_email ? 'var(--bg-elevated)' : 'var(--bg-surface)',
                border: `1px solid ${selectedUser === u.user_email ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                <StatusDot active={!!u.is_online} />
                <span style={{ fontWeight: 600, fontSize: '0.85rem' }}>
                  {displayName(u)}
                </span>
                <Badge label={u.user_role.toUpperCase()} color={ROLE_COLORS[u.user_role] || '#888'} small />
              </div>
              {!isIpAddress(u.user_email) && (
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginBottom: 2 }}>
                  {u.user_email}
                </div>
              )}
              <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', display: 'flex', gap: 12 }}>
                <span>{u.total_messages} msgs</span>
                <span>{u.session_count} sessions</span>
                <span>via {u.last_endpoint}</span>
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: 2 }}>
                Last seen: {timeAgo(u.last_seen)}
                {u.last_latitude != null && u.last_longitude != null && (
                  <span> | {u.last_latitude.toFixed(2)}, {u.last_longitude.toFixed(2)}</span>
                )}
              </div>
            </div>
          ))}
          {users.length === 0 && (
            <div style={{ color: 'var(--text-secondary)', padding: '2rem', textAlign: 'center' }}>
              No users yet — sessions are recorded when users connect via voice or chat.
            </div>
          )}
        </div>
      </div>

      {/* User detail / sessions / tasks */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {selectedUser ? (
          <UserDetail
            user={users.find(u => u.user_email === selectedUser)!}
            sessions={userSessions}
            tasks={userTasks}
          />
        ) : (
          <div style={{ color: 'var(--text-secondary)', padding: '3rem', textAlign: 'center' }}>
            Select a user to view their sessions and activity
          </div>
        )}
      </div>
    </div>
  );
}

function UserDetail({
  user, sessions, tasks,
}: {
  user: UserProfile;
  sessions: Session[];
  tasks: Task[];
}) {
  if (!user) return null;

  return (
    <div>
      {/* Header */}
      <div style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
          <StatusDot active={!!user.is_online} />
          <h3 style={{ fontSize: '1.1rem', fontWeight: 600 }}>{displayName(user)}</h3>
          <Badge label={user.user_role.toUpperCase()} color={ROLE_COLORS[user.user_role] || '#888'} />
          {user.is_online ? (
            <Badge label="ONLINE" color="var(--success)" small />
          ) : (
            <Badge label="OFFLINE" color="var(--text-muted)" small />
          )}
        </div>
        <div style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', display: 'flex', gap: '1.5rem' }}>
          <span>Email: {user.user_email}</span>
          <span>Sessions: {user.session_count}</span>
          <span>Messages: {user.total_messages}</span>
          {user.last_latitude != null && user.last_longitude != null && (
            <span>Location: {user.last_latitude.toFixed(4)}, {user.last_longitude.toFixed(4)}</span>
          )}
        </div>
      </div>

      {/* Sessions */}
      <div style={{ marginBottom: '1.5rem' }}>
        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8 }}>Sessions ({sessions.length})</h4>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
          {sessions.slice(0, 20).map(s => (
            <div key={s.session_id} style={{
              padding: '0.5rem 0.75rem',
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}>
              <StatusDot active={!!s.is_active} />
              <Badge label={s.endpoint.toUpperCase()} color={s.endpoint === 'voice' ? 'var(--accent)' : 'var(--info)'} small />
              <span style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
                {new Date(s.connected_at).toLocaleString()}
              </span>
              <span>{s.message_count} msgs</span>
              {s.latitude != null && s.longitude != null && (
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {s.latitude.toFixed(2)}, {s.longitude.toFixed(2)}
                </span>
              )}
              <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                {s.client_ip}
              </span>
              {s.disconnected_at && (
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  ended {timeAgo(s.disconnected_at)}
                </span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Tasks associated with this user */}
      <div>
        <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8 }}>
          Related Tasks ({tasks.length})
        </h4>
        {tasks.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.3rem' }}>
            {tasks.map(t => (
              <div key={t.id} style={{
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: 8,
              }}>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>#{t.id}</span>
                <Badge label={t.state} color="var(--info)" small />
                {t.assignee && <Badge label={agentLabel(t.assignee)} color={agentColor(t.assignee)} small />}
                <span style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: PRIORITY_COLORS[t.priority] || '#888',
                  display: 'inline-block',
                }} />
                <span style={{ flex: 1 }}>{t.title.slice(0, 60)}{t.title.length > 60 ? '...' : ''}</span>
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{timeAgo(t.created_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <div style={{ color: 'var(--text-secondary)', fontSize: '0.8rem' }}>
            No tasks directly linked to this user yet.
          </div>
        )}
      </div>
    </div>
  );
}
