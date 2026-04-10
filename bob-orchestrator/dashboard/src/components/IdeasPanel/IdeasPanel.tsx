import { useState, useEffect } from 'react';
import { apiFetch } from '../../api/client';
import { Badge } from '../common/Badge';

interface Idea {
  title: string;
  added: string;
  source: string;
  status: string;
  description: string;
  rationale: string;
  requirements: string;
  questions: string;
  bob_notes: string;
}

interface ArchiveEntry {
  idea: string;
  activated: string;
  became: string;
}

const STATUS_COLORS: Record<string, string> = {
  'Parked': '#6b7280',
  'Parked — needs build plan': 'var(--warning)',
  'Parked — execute after Android launch': 'var(--info)',
  'Parked — hidden / unlockable variant': '#a78bfa',
};

function statusColor(status: string): string {
  for (const [key, color] of Object.entries(STATUS_COLORS)) {
    if (status.includes(key)) return color;
  }
  return '#6b7280';
}

export function IdeasPanel() {
  const [ideas, setIdeas] = useState<Idea[]>([]);
  const [archive, setArchive] = useState<ArchiveEntry[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    apiFetch<{ ideas: Idea[]; archive: ArchiveEntry[] }>('/ideas')
      .then(data => { setIdeas(data.ideas); setArchive(data.archive); })
      .catch(e => setError(e.message));
  }, []);

  if (error) {
    return <div style={{ color: 'var(--error)', padding: '2rem' }}>Error: {error}</div>;
  }

  return (
    <div style={{ display: 'flex', gap: '1.5rem', height: 'calc(100vh - 180px)' }}>
      {/* Idea list */}
      <div style={{ width: 360, flexShrink: 0, overflowY: 'auto' }}>
        <h3 style={{ fontSize: '0.9rem', fontWeight: 600, marginBottom: '0.75rem' }}>
          Parking Lot ({ideas.length} ideas)
        </h3>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          {ideas.map((idea, i) => (
            <div
              key={i}
              onClick={() => setSelected(i)}
              style={{
                padding: '0.75rem',
                background: selected === i ? 'var(--bg-elevated)' : 'var(--bg-surface)',
                border: `1px solid ${selected === i ? 'var(--accent)' : 'var(--border)'}`,
                borderRadius: 'var(--radius)',
                cursor: 'pointer',
                borderLeft: `3px solid ${statusColor(idea.status)}`,
              }}
            >
              <div style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 4 }}>
                {idea.title}
              </div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                <Badge label={idea.status || 'Parked'} color={statusColor(idea.status)} small />
                <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                  {idea.added} · {idea.source}
                </span>
              </div>
            </div>
          ))}
        </div>

        {/* Archive section */}
        {archive.length > 0 && (
          <div style={{ marginTop: '1.5rem' }}>
            <h4 style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--accent)', marginBottom: 8 }}>
              Activated Ideas
            </h4>
            {archive.map((a, i) => (
              <div key={i} style={{
                padding: '0.5rem 0.75rem',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-sm)',
                borderLeft: '3px solid var(--success)',
                marginBottom: 4,
                fontSize: '0.8rem',
              }}>
                <div style={{ fontWeight: 500 }}>{a.idea}</div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
                  Activated {a.activated} → {a.became}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Idea detail */}
      <div style={{ flex: 1, overflowY: 'auto' }}>
        {selected !== null && ideas[selected] ? (
          <IdeaDetail idea={ideas[selected]} />
        ) : (
          <div style={{ color: 'var(--text-secondary)', padding: '3rem', textAlign: 'center' }}>
            Select an idea to view details
          </div>
        )}
      </div>
    </div>
  );
}

function IdeaDetail({ idea }: { idea: Idea }) {
  return (
    <div>
      <h3 style={{ fontSize: '1.1rem', fontWeight: 600, marginBottom: 8 }}>{idea.title}</h3>
      <div style={{ display: 'flex', gap: 8, marginBottom: '1rem', flexWrap: 'wrap' }}>
        <Badge label={idea.status || 'Parked'} color={statusColor(idea.status)} />
        <span style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
          Added {idea.added} by {idea.source}
        </span>
      </div>

      <Section title="The Idea" content={idea.description} />
      <Section title="Why It's Worth Doing" content={idea.rationale} />
      <Section title="What It Would Need" content={idea.requirements} />
      <Section title="Open Questions" content={idea.questions} />
      {idea.bob_notes && idea.bob_notes !== '*(none yet)*' && (
        <Section title="BOB Notes" content={idea.bob_notes} accent />
      )}
    </div>
  );
}

function Section({ title, content, accent }: { title: string; content: string; accent?: boolean }) {
  if (!content) return null;
  return (
    <div style={{ marginBottom: '1.25rem' }}>
      <h4 style={{
        fontSize: '0.85rem',
        fontWeight: 600,
        marginBottom: 6,
        color: accent ? 'var(--accent)' : 'var(--text-primary)',
      }}>
        {title}
      </h4>
      <div style={{
        fontSize: '0.83rem',
        lineHeight: 1.6,
        color: 'var(--text-secondary)',
        whiteSpace: 'pre-wrap',
      }}>
        {content}
      </div>
    </div>
  );
}
