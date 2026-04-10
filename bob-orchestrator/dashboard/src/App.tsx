import { DashboardProvider, useDashboard } from './context/DashboardContext';
import { Shell } from './components/Layout/Shell';
import { TaskBoard } from './components/TaskBoard/TaskBoard';
import { AgentGrid } from './components/AgentGrid/AgentGrid';
import { MessageFeed } from './components/MessageFeed/MessageFeed';
import { CostPanel } from './components/CostPanel/CostPanel';
import { UsersPanel } from './components/UsersPanel/UsersPanel';
import { IdeasPanel } from './components/IdeasPanel/IdeasPanel';

function TabContent() {
  const { state } = useDashboard();
  switch (state.activeTab) {
    case 0: return <TaskBoard />;
    case 1: return <AgentGrid />;
    case 2: return <MessageFeed />;
    case 3: return <CostPanel />;
    case 4: return <UsersPanel />;
    case 5: return <IdeasPanel />;
    default: return null;
  }
}

function App() {
  return (
    <DashboardProvider>
      <Shell>
        <TabContent />
      </Shell>
    </DashboardProvider>
  );
}

export default App;
