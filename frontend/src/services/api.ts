const API_BASE_URL = 'http://localhost:8000/api';

interface RefreshResponse {
  access: string;
  refresh: string;
}

let refreshPromise: Promise<string> | null = null;
let logoutInProgress = false;
let sessionAbortController = new AbortController();
let authStateListeners: (() => void)[] = [];

function notifyAuthStateListeners() {
  authStateListeners.forEach((listener) => listener());
}

export const auth = {
  getAccessToken(): string | null {
    return localStorage.getItem('access_token');
  },

  getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token');
  },

  getUserEmail(): string | null {
    return localStorage.getItem('user_email');
  },

  setTokens(access: string, refresh: string, email?: string) {
    localStorage.setItem('access_token', access);
    localStorage.setItem('refresh_token', refresh);
    if (email) {
      localStorage.setItem('user_email', email);
    }
    notifyAuthStateListeners();
  },

  clearTokens() {
    sessionAbortController.abort();
    sessionAbortController = new AbortController();
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user_email');
    notifyAuthStateListeners();
  },

  async logout(): Promise<void> {
    logoutInProgress = true;
    try {
      await refreshPromise?.catch(() => undefined);
      const refresh = this.getRefreshToken();
      if (refresh) {
        const response = await fetch(`${API_BASE_URL}/token/blacklist/`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh }),
          signal: AbortSignal.timeout(10000),
        });
        if (!response.ok && response.status !== 401) {
          const data = await response.json().catch(() => ({}));
          throw new Error(extractErrorMessage(data, 'Logout failed. Please retry.'));
        }
      }
      this.clearTokens();
    } finally {
      logoutInProgress = false;
    }
  },

  isAuthenticated(): boolean {
    return !!this.getAccessToken();
  },

  subscribe(listener: () => void) {
    authStateListeners.push(listener);
    return () => {
      authStateListeners = authStateListeners.filter((l) => l !== listener);
    };
  },
};

async function forceRefreshToken(): Promise<string> {
  const refresh = auth.getRefreshToken();
  if (!refresh) {
    throw new Error('No refresh token available');
  }

  const response = await fetch(`${API_BASE_URL}/token/refresh/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh }),
    signal: AbortSignal.any([sessionAbortController.signal, AbortSignal.timeout(10000)]),
  });

  if (!response.ok) {
    if (response.status === 401) {
      auth.clearTokens();
      throw new Error('Session expired');
    }
    const data = await response.json().catch(() => ({}));
    throw new Error(extractErrorMessage(data, 'Could not refresh the session. Please retry.'));
  }

  const data: RefreshResponse = await response.json();
  auth.setTokens(data.access, data.refresh);
  return data.access;
}

async function request(path: string, options: RequestInit = {}): Promise<Response> {
  const url =
    path.startsWith('http://') || path.startsWith('https://') ? path : `${API_BASE_URL}${path}`;
  const headers = new Headers(options.headers || {});

  const token = auth.getAccessToken();
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }

  if (!headers.has('Content-Type') && !(options.body instanceof FormData)) {
    headers.set('Content-Type', 'application/json');
  }

  const config = { ...options, headers, signal: options.signal ?? sessionAbortController.signal };
  const response = await fetch(url, config);

  if (response.status === 401 && auth.getRefreshToken() && !logoutInProgress) {
    let newToken = auth.getAccessToken();
    if (!newToken || newToken === token) {
      refreshPromise ??= forceRefreshToken().finally(() => {
        refreshPromise = null;
      });
      newToken = await refreshPromise;
    }
    config.signal.throwIfAborted();
    headers.set('Authorization', `Bearer ${newToken}`);
    return fetch(url, config);
  }

  return response;
}

function extractErrorMessage(errData: unknown, defaultMsg: string): string {
  if (!errData || typeof errData !== 'object') {
    return defaultMsg;
  }
  const errObj = errData as Record<string, unknown>;
  if (errObj.error) return String(errObj.error);
  if (errObj.message) return String(errObj.message);
  if (errObj.detail) return String(errObj.detail);
  const fieldErrors: string[] = [];
  for (const [key, val] of Object.entries(errObj)) {
    const fieldName = key.replace(/_/g, ' ');
    const formattedFieldName = fieldName.charAt(0).toUpperCase() + fieldName.slice(1);
    if (Array.isArray(val)) {
      fieldErrors.push(`• ${formattedFieldName}: ${val.join(' ')}`);
    } else if (typeof val === 'string') {
      fieldErrors.push(`• ${formattedFieldName}: ${val}`);
    }
  }
  if (fieldErrors.length > 0) {
    return fieldErrors.join('\n');
  }
  return defaultMsg;
}

interface ParsedEvent {
  type: 'token' | 'done' | 'compaction_done' | 'error';
  content?: string;
  variant?: 'rag_on' | 'rag_off';
  message?: string;
  message_id?: string;
  title?: string;
  usage?: unknown;
}

function safeJsonParse(str: string): ParsedEvent | null {
  try {
    return JSON.parse(str) as ParsedEvent;
  } catch (err) {
    console.warn('Failed to parse JSON string:', str, err);
    return null;
  }
}

export const api = {
  async get<T>(path: string): Promise<T> {
    const response = await request(path, { method: 'GET' });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(extractErrorMessage(errData, `GET request failed: ${response.statusText}`));
    }
    return response.json();
  },

  async post<T>(path: string, body: unknown): Promise<T> {
    const response = await request(path, {
      method: 'POST',
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(extractErrorMessage(errData, `POST request failed: ${response.statusText}`));
    }
    return response.json();
  },

  async patch<T>(path: string, body: unknown): Promise<T> {
    const response = await request(path, {
      method: 'PATCH',
      body: body instanceof FormData ? body : JSON.stringify(body),
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(extractErrorMessage(errData, `PATCH request failed: ${response.statusText}`));
    }
    return response.json();
  },

  async delete(path: string): Promise<void> {
    const response = await request(path, { method: 'DELETE' });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(
        extractErrorMessage(errData, `DELETE request failed: ${response.statusText}`)
      );
    }
  },

  async stream(
    path: string,
    body: unknown,
    onToken: (token: string, variant?: 'rag_on' | 'rag_off') => void,
    onDone: (data: unknown) => void,
    onCompactionDone: (data: unknown) => void,
    onError: (error: string) => void,
    signal?: AbortSignal
  ) {
    try {
      const response = await request(path, {
        method: 'POST',
        body: JSON.stringify(body),
        signal,
      });

      if (!response.ok) {
        const errText = await response.text().catch(() => '');
        let errMsg = `Stream request failed: ${response.statusText}`;
        if (errText.trim().startsWith('data: ')) {
          try {
            const event = JSON.parse(errText.trim().slice(6));
            if (event.message) {
              errMsg = event.message;
            }
          } catch (err) {
            console.error('Failed to parse error stream event:', err);
          }
        } else {
          try {
            const json = JSON.parse(errText);
            errMsg = json.error || json.message || errMsg;
          } catch (err) {
            console.error('Failed to parse error response JSON:', err);
          }
        }
        onError(errMsg);
        return;
      }

      if (!response.body) {
        onError('Response body is null');
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed.startsWith('data: ')) {
            continue;
          }

          const rawData = trimmed.slice(6);
          const event = safeJsonParse(rawData);
          if (!event) {
            continue;
          }

          if (event.type === 'token') {
            onToken(event.content ?? '', event.variant);
          } else if (event.type === 'done') {
            onDone(event);
          } else if (event.type === 'compaction_done') {
            onCompactionDone(event);
          } else if (event.type === 'error') {
            onError(event.message ?? 'Unknown streaming error');
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        return;
      }
      onError(err instanceof Error ? err.message : String(err));
    }
  },
};
