import { useMemo, useRef, useEffect } from 'react';
import { useDashboard } from '../../context/DashboardContext';
import { MessageItem } from './MessageItem';
import { MessageFilters } from './MessageFilters';

export function MessageFeed() {
  const { state } = useDashboard();
  const containerRef = useRef<HTMLDivElement>(null);
  const wasAtBottom = useRef(true);

  const filtered = useMemo(() => {
    let msgs = [...state.messages].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    );
    const f = state.messageFilters;
    if (f.sender) msgs = msgs.filter(m => m.sender === f.sender);
    if (f.messageType) msgs = msgs.filter(m => m.message_type === f.messageType);
    if (f.taskId) msgs = msgs.filter(m => m.task_id?.toString() === f.taskId);
    return msgs;
  }, [state.messages, state.messageFilters]);

  useEffect(() => {
    const el = containerRef.current;
    if (el && wasAtBottom.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [filtered]);

  const handleScroll = () => {
    const el = containerRef.current;
    if (el) {
      wasAtBottom.current = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    }
  };

  return (
    <div>
      <MessageFilters />
      <div
        ref={containerRef}
        onScroll={handleScroll}
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '0.4rem',
          maxHeight: 'calc(100vh - 220px)',
          overflowY: 'auto',
        }}
      >
        {filtered.map(msg => (
          <MessageItem key={msg.id} msg={msg} />
        ))}
        {filtered.length === 0 && (
          <div style={{ color: 'var(--text-secondary)', padding: '2rem', textAlign: 'center' }}>
            No messages
          </div>
        )}
      </div>
    </div>
  );
}
