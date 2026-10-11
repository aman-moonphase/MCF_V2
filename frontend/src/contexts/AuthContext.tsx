"use client";

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { apiClient } from '@/lib/api-client';
import { isSessionRejected } from '@/lib/api-errors';

interface User {
  id: number;
  email: string;
  isActive: boolean;
  isSuperuser: boolean;
}

interface AuthContextType {
  user: User | null;
  isLoading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => void;
  checkAuth: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  // The server could not be reached (or failed) while checking the session: the saved session is kept, not discarded.
  const [serverUnreachable, setServerUnreachable] = useState(false);
  const router = useRouter();
  const pathname = usePathname();

  const checkAuth = async () => {
    // Yield to the event loop to prevent synchronous setState in useEffect, 
    // which causes cascading render warnings and can get stuck in StrictMode.
    await Promise.resolve();
    
    try {
      const token = localStorage.getItem('access_token');
      if (!token) {
        setUser(null);
        setServerUnreachable(false);
        return;
      }
      
      const userData = await apiClient.get('/auth/me');
      setUser(userData);
      setServerUnreachable(false);
    } catch (error) {
      console.error('Auth check failed:', error);
      setUser(null);
      if (isSessionRejected(error)) {
        setServerUnreachable(false);
        localStorage.removeItem('access_token');  // the server said this session is not valid
      } else {
        setServerUnreachable(true);  // backend down / restarting: keep the session so Try again can restore it
      }
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    checkAuth();
  }, []);

  useEffect(() => {
    if (!isLoading && !serverUnreachable) {
      const publicRoutes = ['/login', '/register', '/forgot-password', '/reset-password'];
      if (!user && !publicRoutes.includes(pathname)) {
        router.push('/login');
      } else if (user && publicRoutes.includes(pathname)) {
        router.push('/');
      }
    }
  }, [user, isLoading, serverUnreachable, pathname, router]);

  const login = async (token: string) => {
    localStorage.setItem('access_token', token);
    await checkAuth();
  };

  const logout = () => {
    localStorage.removeItem('access_token');
    setUser(null);
    router.push('/login');
  };

  return (
    <AuthContext.Provider value={{ user, isLoading, login, logout, checkAuth }}>
      {isLoading ? (
        <div className="fixed inset-0 flex items-center justify-center bg-background z-50">
          <div className="flex flex-col items-center gap-4">
            <div className="h-10 w-10 animate-spin rounded-full border-4 border-primary border-t-transparent shadow-md" />
            <p className="text-sm text-muted-foreground font-medium animate-pulse">Initializing Workspace...</p>
          </div>
        </div>
      ) : serverUnreachable ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-background p-6">
          <div role="alert" className="max-w-md space-y-4 text-center">
            <h2 className="text-xl font-semibold text-foreground">Can&apos;t reach the server</h2>
            <p className="text-sm text-muted-foreground">
              MCF could not contact the backend. You are still signed in — nothing was lost. Check that the server is
              running, then try again.
            </p>
            <button
              type="button"
              onClick={() => { setIsLoading(true); void checkAuth(); }}
              className="inline-flex h-10 items-center rounded-full bg-primary px-5 text-sm font-medium text-primary-foreground"
            >
              Try again
            </button>
          </div>
        </div>
      ) : (
        children
      )}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
