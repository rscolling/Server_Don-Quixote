import { createContext, useContext, useEffect, useReducer, useSyncExternalStore, type ReactNode } from 'react';
import type { Task, Message, Agent, Stats, BusHealth, WsPayload } from '../api/types';
import { wsManager } from '../api/websocket';

interface DashboardState {
  tasks: Task[];
  messages: Message[];
  agents: Agent[];
  stats: Stats | null;
  busHealth: BusHealth | null;
  activeTab: number;
  taskFilters: { assignee: string; priority: string; search: string; user: string };
  messageFilters: { sender: string; messageType: string; taskId: string };
}

type Action =
  | { type: 'WS_UPDATE'; payload: WsPayload }
  | { type: 'SET_TAB'; tab: number }
  | { type: 'SET_TASK_FILTER'; key: string; value: string }
  | { type: 'SET_MESSAGE_FILTER'; key: string; value: string };

const initial: DashboardState = {
  tasks: [],
  messages: [],
  agents: [],
  stats: null,
  busHealth: null,
  activeTab: 0,
  taskFilters: { assignee: '', priority: '', search: '', user: '' },
  messageFilters: { sender: '', messageType: '', taskId: '' },
};

function reducer(state: DashboardState, action: Action): DashboardState {
  switch (action.type) {
    case 'WS_UPDATE':
      return {
        ...state,
        tasks: action.payload.tasks,
        messages: action.payload.messages,
        agents: action.payload.agents,
        stats: action.payload.stats,
        busHealth: action.payload.health,
      };
    case 'SET_TAB':
      return { ...state, activeTab: action.tab };
    case 'SET_TASK_FILTER':
      return { ...state, taskFilters: { ...state.taskFilters, [action.key]: action.value } };
    case 'SET_MESSAGE_FILTER':
      return { ...state, messageFilters: { ...state.messageFilters, [action.key]: action.value } };
    default:
      return state;
  }
}

const Ctx = createContext<{ state: DashboardState; dispatch: React.Dispatch<Action>; wsState: string }>({
  state: initial,
  dispatch: () => {},
  wsState: 'disconnected',
});

export function DashboardProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initial);

  const wsState = useSyncExternalStore(
    (cb) => wsManager.onStateChange(cb),
    () => wsManager.state,
  );

  useEffect(() => {
    wsManager.connect();
    return wsManager.subscribe((data) => {
      dispatch({ type: 'WS_UPDATE', payload: data });
    });
  }, []);

  return (
    <Ctx.Provider value={{ state, dispatch, wsState }}>
      {children}
    </Ctx.Provider>
  );
}

export function useDashboard() {
  return useContext(Ctx);
}
