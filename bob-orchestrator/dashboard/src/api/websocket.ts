import type { WsPayload } from './types';

type Listener = (data: WsPayload) => void;

export class WsManager {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private retryDelay = 1000;
  private maxRetry = 30000;
  private _state: 'connecting' | 'connected' | 'disconnected' = 'disconnected';
  private stateListeners = new Set<() => void>();

  get state() { return this._state; }

  private setState(s: typeof this._state) {
    this._state = s;
    this.stateListeners.forEach(fn => fn());
  }

  connect() {
    if (this.ws) return;
    this.setState('connecting');
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.ws = new WebSocket(`${proto}//${location.host}/dashboard/api/ws`);

    this.ws.onopen = () => {
      this.setState('connected');
      this.retryDelay = 1000;
    };

    this.ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data) as WsPayload;
        this.listeners.forEach(fn => fn(data));
      } catch { /* ignore parse errors */ }
    };

    this.ws.onclose = () => {
      this.ws = null;
      this.setState('disconnected');
      setTimeout(() => this.connect(), this.retryDelay);
      this.retryDelay = Math.min(this.retryDelay * 2, this.maxRetry);
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  subscribe(fn: Listener) {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  onStateChange(fn: () => void) {
    this.stateListeners.add(fn);
    return () => { this.stateListeners.delete(fn); };
  }
}

export const wsManager = new WsManager();
