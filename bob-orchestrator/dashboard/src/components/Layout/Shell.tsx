import type { ReactNode } from 'react';
import { Header } from './Header';
import { TabBar } from './TabBar';

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <Header />
      <TabBar />
      <main style={{ flex: 1, padding: '1rem 1.5rem', overflow: 'auto' }}>
        {children}
      </main>
    </div>
  );
}
