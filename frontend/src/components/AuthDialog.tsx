import { useState, type SubmitEvent } from 'react';
import { api, auth } from '../services/api';
import './AuthDialog.css';
import { Icon } from './Icon';
import { Modal } from './Modal';
import { useAuthStore } from '../stores/useAuthStore';

export function AuthDialog() {
  const isOpen = useAuthStore((s) => s.authDialogOpen);
  const onClose = useAuthStore((s) => s.closeAuthDialog);
  const tab = useAuthStore((s) => s.authDialogTab);
  const setTab = useAuthStore((s) => s.setAuthDialogTab);

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [passwordConfirm, setPasswordConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleClose = () => {
    setError(null);
    setEmail('');
    setPassword('');
    setPasswordConfirm('');
    onClose();
  };

  const handleSubmit = async (e: SubmitEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    const cleanEmail = email.trim();
    if (!cleanEmail || !password) {
      setError('Please fill in all fields.');
      setLoading(false);
      return;
    }

    try {
      if (tab === 'register') {
        if (password !== passwordConfirm) {
          setError('Passwords do not match.');
          setLoading(false);
          return;
        }

        await api.post('/register/', {
          email: cleanEmail,
          password,
          password_confirm: passwordConfirm,
        });
      }

      const tokenData = await api.post<{ access: string; refresh: string }>('/token/', {
        email: cleanEmail,
        password,
      });

      auth.setTokens(tokenData.access, tokenData.refresh, cleanEmail);
      handleClose();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={handleClose} id="auth-popover" className="auth-dialog">
      <div className="auth-dialog-wrapper">
        <div className="auth-dialog-header modal-header">
          <div className="auth-dialog-tabs">
            <button
              type="button"
              className={`auth-dialog-tab-btn ${tab === 'login' ? 'active' : ''}`}
              onClick={() => {
                setTab('login');
                setError(null);
              }}
            >
              Login
            </button>
            <button
              type="button"
              className={`auth-dialog-tab-btn ${tab === 'register' ? 'active' : ''}`}
              onClick={() => {
                setTab('register');
                setError(null);
              }}
            >
              Register
            </button>
          </div>
          <button
            type="button"
            className="modal-close-btn"
            aria-label="Close authentication dialog"
            onClick={handleClose}
          >
            <Icon name="x" size={16} />
          </button>
        </div>

        <form className="auth-dialog-form" onSubmit={handleSubmit}>
          {error ? (
            <div className="error-banner" role="alert">
              {error}
            </div>
          ) : null}

          <div className="form-field">
            <label htmlFor="auth-email">Email</label>
            <input
              id="auth-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
              autoComplete="email"
            />
          </div>

          <div className="form-field">
            <label htmlFor="auth-password">Password</label>
            <input
              id="auth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              required
              autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
            />
          </div>

          {tab === 'register' ? (
            <div className="form-field">
              <label htmlFor="auth-password-confirm">Confirm Password</label>
              <input
                id="auth-password-confirm"
                type="password"
                value={passwordConfirm}
                onChange={(e) => setPasswordConfirm(e.target.value)}
                placeholder="••••••••"
                required={tab === 'register'}
                autoComplete="new-password"
              />
            </div>
          ) : null}

          <button type="submit" className="btn-primary auth-dialog-submit-btn" disabled={loading}>
            {loading ? 'Processing...' : tab === 'login' ? 'Log In' : 'Sign Up'}
          </button>
        </form>
      </div>
    </Modal>
  );
}
