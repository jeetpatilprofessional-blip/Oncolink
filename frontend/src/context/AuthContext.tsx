import React, { useEffect, useState } from "react";
import {
  getMe,
  login as apiLogin,
  login2fa as apiLogin2fa,
  logout as apiLogout,
  onAuthFailure,
  refreshSession,
  setAccessToken,
} from "../api/client";
import type { LoginResponse, User } from "../api/types";
import { AuthContext } from "./auth-context-def";

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  const refreshUser = async (): Promise<User | null> => {
    try {
      const profile = await getMe();
      setUser(profile);
      return profile;
    } catch {
      setUser(null);
      return null;
    }
  };

  useEffect(() => {
    let mounted = true;

    const initAuth = async () => {
      try {
        const token = await refreshSession();
        if (token && mounted) {
          const profile = await getMe();
          if (mounted) {
            setUser(profile);
          }
        }
      } catch {
        if (mounted) {
          setUser(null);
          setAccessToken(null);
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    initAuth();

    const unsubscribe = onAuthFailure(() => {
      if (mounted) {
        setUser(null);
        setAccessToken(null);
      }
    });

    return () => {
      mounted = false;
      unsubscribe();
    };
  }, []);

  const login = async (email: string, password: string): Promise<LoginResponse> => {
    const res = await apiLogin(email, password);
    if (res.access_token) {
      const profile = await getMe();
      setUser(profile);
    }
    return res;
  };

  const login2fa = async (
    tempToken: string,
    code?: string,
    recoveryCode?: string
  ): Promise<LoginResponse> => {
    const res = await apiLogin2fa(tempToken, code, recoveryCode);
    if (res.access_token) {
      const profile = await getMe();
      setUser(profile);
    }
    return res;
  };

  const logout = async (): Promise<void> => {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        isAuthenticated: !!user,
        login,
        login2fa,
        logout,
        setUser,
        refreshUser,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};
