import { useState, useEffect } from 'react';
import { apiFetch } from '../../api/client';
import type { CostStatus, RouterStatus } from '../../api/types';
import { ProgressBar } from '../common/ProgressBar';
import { Badge } from '../common/Badge';

export function CostPanel() {
  const [cost, setCost] = useState<CostStatus | null>(null);
  const [router, setRouter] = useState<RouterStatus | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const fetch = async () => {
      try {
        const [c, r] = await Promise.all([
          apiFetch<CostStatus>('/cost'),
          apiFetch<RouterStatus>('/router'),
        ]);
        setCost(c);
        setRouter(r);
        setError('');
      } catch (e: any) {
        setError(e.message);
      }
    };
    fetch();
    const interval = setInterval(fetch, 30000);
    return () => clearInterval(interval);
  }, []);

  if (error) {
    return <div style={{ color: 'var(--error)', padding: '2rem' }}>Error loading cost data: {error}</div>;
  }

  if (!cost) {
    return <div style={{ color: 'var(--text-secondary)', padding: '2rem' }}>Loading cost data...</div>;
  }

  return (
    <div style={{ maxWidth: 800 }}>
      <h3 style={{ fontSize: '0.95rem', fontWeight: 600, marginBottom: '1rem' }}>Budget</h3>
      <ProgressBar value={cost.daily_spend} max={cost.daily_budget} label="Daily" />
      <ProgressBar value={cost.monthly_spend} max={cost.monthly_budget} label="Monthly" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem', marginTop: '1.5rem' }}>
        <div>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8 }}>Spend by User</h4>
          <table style={{ width: '100%', fontSize: '0.8rem', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 0' }}>User</th>
                <th style={{ textAlign: 'right', padding: '4px 0' }}>Cost</th>
                <th style={{ textAlign: 'right', padding: '4px 0' }}>Calls</th>
              </tr>
            </thead>
            <tbody>
              {(cost.by_user || []).map((u, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '4px 0' }}>{u.user}</td>
                  <td style={{ textAlign: 'right', padding: '4px 0' }}>${u.cost_usd.toFixed(4)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 0' }}>{u.calls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8 }}>Spend by Model</h4>
          <table style={{ width: '100%', fontSize: '0.8rem', borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                <th style={{ textAlign: 'left', padding: '4px 0' }}>Model</th>
                <th style={{ textAlign: 'right', padding: '4px 0' }}>Cost</th>
                <th style={{ textAlign: 'right', padding: '4px 0' }}>Calls</th>
              </tr>
            </thead>
            <tbody>
              {(cost.by_model || []).map((m, i) => (
                <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '4px 0' }}>{m.model}</td>
                  <td style={{ textAlign: 'right', padding: '4px 0' }}>${m.cost_usd.toFixed(4)}</td>
                  <td style={{ textAlign: 'right', padding: '4px 0' }}>{m.calls}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {router && (
        <div style={{ marginTop: '1.5rem' }}>
          <h4 style={{ fontSize: '0.85rem', fontWeight: 600, marginBottom: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
            Model Router
            <Badge label={router.enabled ? 'ENABLED' : 'DISABLED'} color={router.enabled ? 'var(--success)' : 'var(--error)'} small />
          </h4>
          {router.enabled && router.tiers && (
            <div style={{ fontSize: '0.8rem' }}>
              <span style={{ color: 'var(--text-secondary)' }}>Provider: </span>{router.provider}
              <table style={{ width: '100%', fontSize: '0.8rem', borderCollapse: 'collapse', marginTop: 8 }}>
                <thead>
                  <tr style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)' }}>
                    <th style={{ textAlign: 'left', padding: '4px 0' }}>Tier</th>
                    <th style={{ textAlign: 'left', padding: '4px 0' }}>Model</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(router.tiers).map(([tier, model]) => (
                    <tr key={tier} style={{ borderBottom: '1px solid var(--border)' }}>
                      <td style={{ padding: '4px 0', textTransform: 'uppercase' }}>{tier}</td>
                      <td style={{ padding: '4px 0', fontFamily: 'monospace', fontSize: '0.75rem' }}>{model}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
