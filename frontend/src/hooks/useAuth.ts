import { useState, useEffect } from 'react';
import { auth } from '../services/api';

export function useAuth() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => auth.isAuthenticated());
  const [userEmail, setUserEmail] = useState(() => auth.getUserEmail());

  useEffect(() => {
    return auth.subscribe(() => {
      setIsAuthenticated(auth.isAuthenticated());
      setUserEmail(auth.getUserEmail());
    });
  }, []);

  const logout = () => {
    auth.clearTokens();
  };

  return {
    isAuthenticated,
    userEmail,
    logout,
  };
}
