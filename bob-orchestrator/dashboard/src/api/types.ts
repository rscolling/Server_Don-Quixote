export interface Task {
  id: number;
  title: string;
  description: string;
  assignee: string | null;
  state: TaskState;
  priority: Priority;
  file_paths: string[];
  metadata: Record<string, any>;
  created_at: string;
  updated_at: string;
  watchers: string[];
}

export type TaskState =
  | 'CREATED'
  | 'ASSIGNED'
  | 'IN_PROGRESS'
  | 'IN_REVIEW'
  | 'REWORK'
  | 'ACCEPTED'
  | 'CLOSED';

export type Priority = 'low' | 'normal' | 'high' | 'critical';

export interface Message {
  id: number;
  sender: string;
  recipient: string;
  message_type: string;
  priority: Priority;
  payload: Record<string, any>;
  context: Record<string, any>;
  task_id: number | null;
  timestamp: string;
  reply_to: number | null;
  thread_id: number | null;
  topic: string | null;
}

export interface Agent {
  shorthand: string;
  name: string;
  role: string;
  status: string;
  registered_at: string;
  last_seen: string | null;
  is_active: boolean;
  capabilities: Capability[];
}

export interface Capability {
  id: number;
  agent: string;
  name: string;
  version: string;
  metadata: Record<string, any>;
}

export interface Stats {
  messages: { total: number; by_type: Record<string, number> };
  tasks: { total: number; by_state: Record<string, number> };
  agents: { total: number; active: number };
  subscriptions: { total: number; topics: number };
}

export interface BusHealth {
  status: string;
  uptime_seconds: number;
  db_size_bytes: number;
  version: string;
}

export interface WsPayload {
  type: 'update';
  health: BusHealth;
  stats: Stats;
  messages: Message[];
  tasks: Task[];
  agents: Agent[];
  topics: { topic: string; subscriber_count: number; subscribers: string[] }[];
}

export interface CostStatus {
  daily_spend: number;
  daily_budget: number;
  monthly_spend: number;
  monthly_budget: number;
  by_user: { user: string; cost_usd: number; calls: number }[];
  by_model: { model: string; cost_usd: number; calls: number }[];
}

export interface RouterStatus {
  enabled: boolean;
  provider?: string;
  tiers?: Record<string, string>;
}

export interface BobHealth {
  status: string;
  persona: string;
  uptime_seconds: number;
  graph_ready: boolean;
  bus_queue_depth: number;
  elevenlabs?: Record<string, any>;
  circuit_breakers?: Record<string, any>;
  cost?: Record<string, any>;
  loop_detector?: Record<string, any>;
}

// Agent shorthand display mapping
export const AGENT_LABELS: Record<string, string> = {
  PM: 'PROJ',
  RA: 'RSRCH',
  CE: 'COPY',
  QA: 'QATST',
  SE: 'SYSEG',
  RE: 'RELENG',
  FE: 'FRONT',
  BE: 'BACK',
  ORCH: 'BOB',
};

export const AGENT_COLORS: Record<string, string> = {
  PM: '#60a5fa',
  RA: '#a78bfa',
  CE: '#f472b6',
  QA: '#fb923c',
  SE: '#4ecca3',
  RE: '#fbbf24',
  FE: '#34d399',
  BE: '#818cf8',
  ORCH: '#4ecca3',
};

export const PRIORITY_COLORS: Record<string, string> = {
  low: '#6b7280',
  normal: '#60a5fa',
  high: '#fb923c',
  critical: '#f87171',
};

export const KANBAN_COLUMNS: TaskState[] = [
  'CREATED',
  'ASSIGNED',
  'IN_PROGRESS',
  'IN_REVIEW',
  'ACCEPTED',
  'CLOSED',
];

export function agentLabel(shorthand: string): string {
  return AGENT_LABELS[shorthand] || shorthand;
}

export function agentColor(shorthand: string): string {
  return AGENT_COLORS[shorthand] || '#888';
}
