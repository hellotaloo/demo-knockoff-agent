# Frontend Authentication Guide

Quick guide for integrating authentication in the Taloo frontend.

## Overview

- **Auth Provider**: Supabase Auth with Google OAuth
- **Token Type**: JWT (HS256)
- **Token Expiry**: 24 hours (dev-login) / 1 hour (production)
- **Multi-Workspace**: Users can belong to multiple workspaces

---

## Quick Start (Local Development)

For local development, use the **dev-login** endpoint to skip Google OAuth:

```typescript
// Login without Google popup
const devLogin = async () => {
  const res = await fetch('http://localhost:8080/auth/dev-login', {
    method: 'POST',
  });
  const data = await res.json();

  // Store credentials
  localStorage.setItem('access_token', data.access_token);
  localStorage.setItem('user', JSON.stringify(data.user));
  localStorage.setItem('workspaces', JSON.stringify(data.workspaces));

  // Set default workspace (first one)
  if (data.workspaces.length > 0) {
    localStorage.setItem('workspace_id', data.workspaces[0].id);
  }

  return data;
};
```

**Dev Login Button (only show in development):**

```tsx
{process.env.NODE_ENV === 'development' && (
  <button onClick={devLogin} className="dev-login-btn">
    Dev Login (skip Google)
  </button>
)}
```

---

## Production Auth Flow (Google OAuth)

```typescript
// 1. Redirect to Google login
const loginWithGoogle = () => {
  window.location.href = `${API_URL}/auth/login/google`;
};

// 2. Handle callback (on your /auth/callback page)
const handleCallback = async () => {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');

  if (code) {
    const res = await fetch(`${API_URL}/auth/callback?code=${code}`);
    const data = await res.json();

    // Store credentials (same as dev-login)
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('refresh_token', data.refresh_token);
    localStorage.setItem('user', JSON.stringify(data.user));
    localStorage.setItem('workspaces', JSON.stringify(data.workspaces));

    // Redirect to dashboard
    router.push('/dashboard');
  }
};
```

---

## Making Authenticated Requests

All API requests to protected endpoints need:

```typescript
const apiCall = async (endpoint: string, options: RequestInit = {}) => {
  const token = localStorage.getItem('access_token');
  const workspaceId = localStorage.getItem('workspace_id');

  const res = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      ...options.headers,
      'Authorization': `Bearer ${token}`,
      'X-Workspace-ID': workspaceId || '',
      'Content-Type': 'application/json',
    },
  });

  if (res.status === 401) {
    // Token expired - redirect to login
    localStorage.clear();
    router.push('/login');
    return null;
  }

  return res.json();
};
```

---

## Get Current User

```typescript
const getCurrentUser = async () => {
  const token = localStorage.getItem('access_token');

  const res = await fetch(`${API_URL}/auth/me`, {
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  if (!res.ok) {
    throw new Error('Not authenticated');
  }

  return res.json();
  // Returns: { user: UserProfile, workspaces: WorkspaceSummary[] }
};
```

---

## Workspace Switching

Users can belong to multiple workspaces. Let them switch:

```tsx
const WorkspaceSwitcher = ({ workspaces, currentId, onSwitch }) => (
  <select
    value={currentId}
    onChange={(e) => {
      localStorage.setItem('workspace_id', e.target.value);
      onSwitch(e.target.value);
    }}
  >
    {workspaces.map(ws => (
      <option key={ws.id} value={ws.id}>
        {ws.name} ({ws.role})
      </option>
    ))}
  </select>
);
```

---

## Logout

```typescript
const logout = async () => {
  const token = localStorage.getItem('access_token');

  await fetch(`${API_URL}/auth/logout`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
    },
  });

  localStorage.clear();
  router.push('/login');
};
```

---

## Types

```typescript
interface UserProfile {
  id: string;
  email: string;
  full_name: string;
  avatar_url?: string;
  phone?: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  logo_url?: string;
  role: 'owner' | 'admin' | 'member';
}

interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: 'bearer';
  expires_in: number;
  user: UserProfile;
  workspaces: WorkspaceSummary[];
}
```

---

## Environment Variables

```env
# Frontend .env
NEXT_PUBLIC_API_URL=http://localhost:8080
```

---

## Auth Context (React Example)

```tsx
// contexts/AuthContext.tsx
import { createContext, useContext, useEffect, useState } from 'react';

interface AuthContextType {
  user: UserProfile | null;
  workspaces: WorkspaceSummary[];
  currentWorkspace: string | null;
  isLoading: boolean;
  login: () => void;
  devLogin: () => Promise<void>;
  logout: () => void;
  switchWorkspace: (id: string) => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [currentWorkspace, setCurrentWorkspace] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Check for existing session on mount
    const token = localStorage.getItem('access_token');
    if (token) {
      getCurrentUser()
        .then(data => {
          setUser(data.user);
          setWorkspaces(data.workspaces);
          setCurrentWorkspace(localStorage.getItem('workspace_id'));
        })
        .catch(() => localStorage.clear())
        .finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = () => {
    window.location.href = `${API_URL}/auth/login/google`;
  };

  const devLogin = async () => {
    const res = await fetch(`${API_URL}/auth/dev-login`, { method: 'POST' });
    const data = await res.json();
    localStorage.setItem('access_token', data.access_token);
    localStorage.setItem('workspace_id', data.workspaces[0]?.id);
    setUser(data.user);
    setWorkspaces(data.workspaces);
    setCurrentWorkspace(data.workspaces[0]?.id);
  };

  const logout = async () => {
    await fetch(`${API_URL}/auth/logout`, {
      method: 'POST',
      headers: { 'Authorization': `Bearer ${localStorage.getItem('access_token')}` },
    });
    localStorage.clear();
    setUser(null);
    setWorkspaces([]);
    setCurrentWorkspace(null);
  };

  const switchWorkspace = (id: string) => {
    localStorage.setItem('workspace_id', id);
    setCurrentWorkspace(id);
  };

  return (
    <AuthContext.Provider value={{
      user, workspaces, currentWorkspace, isLoading,
      login, devLogin, logout, switchWorkspace,
    }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
```

---

## Summary

| Environment | Login Method | Token Expiry |
|-------------|--------------|--------------|
| Local (`ENVIRONMENT=local`) | `POST /auth/dev-login` | 24 hours |
| Production | Google OAuth via `/auth/login/google` | 1 hour |

**Required Headers for Protected Endpoints:**
- `Authorization: Bearer <token>`
- `X-Workspace-ID: <workspace_uuid>` (for workspace-scoped data)
