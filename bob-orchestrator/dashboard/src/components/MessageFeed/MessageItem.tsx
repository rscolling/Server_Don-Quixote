import { useState } from 'react';
import type { Message } from '../../api/types';
import { agentLabel, agentColor } from '../../api/types';
import { Badge } from '../common/Badge';

const TYPE_COLORS: Record<string, string> = {
  escalation: 'var(--warning)',
  state_change: 'var(--info)',
  deliverable: 'var(--success)',
  feedback: '#a78bfa',
  question: '#fbbf24',
  task_assignment: 'var(--accent)',
  status_update: 'var(--text-secondary)',
};

export function MessageItem({ msg }: { msg: Message }) {
  const [expanded, setExpanded] = useState(false);
  const borderColor = TYPE_COLORS[msg.message_type] || 'transparent';
  const payloadText = msg.payload ? JSON.stringify(msg.payload, null, 2) : '';
  const preview = payloadText.length > 120 ? payloadText.slice(0, 120) + '...' : payloadText;
  const ts = new Date(msg.timestamp).toLocaleTimeString();

  return (
    <div
      onClick={() => setExpanded(!expanded)}
      style={{
        padding: '0.5rem 0.75rem',
        borderLeft: `3px solid ${borderColor}`,
        background: 'var(--bg-surface)',
        borderRadius: '0 var(--radius-sm) var(--radius-sm) 0',
        cursor: payloadText.length > 120 ? 'pointer' : 'default',
        fontSize: '0.8rem',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', minWidth: 60 }}>{ts}</span>
        <Badge label={agentLabel(msg.sender)} color={agentColor(msg.sender)} small />
        <span style={{ color: 'var(--text-muted)' }}>→</span>
        <Badge label={agentLabel(msg.recipient)} color={agentColor(msg.recipient)} small />
        <Badge label={msg.message_type} color={borderColor} small />
        {msg.task_id && (
          <span style={{ fontSize: '0.65rem', color: 'var(--text-secondary)' }}>#{msg.task_id}</span>
        )}
      </div>
      {payloadText && (
        <div style={{
          fontSize: '0.75rem',
          color: 'var(--text-secondary)',
          fontFamily: 'monospace',
          whiteSpace: expanded ? 'pre-wrap' : 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {expanded ? payloadText : preview}
        </div>
      )}
    </div>
  );
}
