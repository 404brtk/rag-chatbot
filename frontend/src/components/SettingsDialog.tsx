import {
  useState,
  useEffect,
  useRef,
  useCallback,
  type SubmitEvent,
  type ChangeEvent,
} from 'react';
import { api, auth } from '../services/api';
import './SettingsDialog.css';
import { Icon } from './Icon';
import type { DocumentData, CursorPaginated } from '../types';
import { formatProviderName, formatCapitalized } from '../utils/format';
import { CustomDropdown } from './CustomDropdown';
import { Modal } from './Modal';

import { useUIStore } from '../stores/useUIStore';

interface ApiKey {
  id: string;
  provider: string;
  masked_key: string;
  created_at: string;
}

interface GetDocsJobData {
  id: string;
  url: string | null;
  github_repo: string | null;
  status: string;
  language: string;
  pages_fetched: number;
  pages_total: number | null;
  created_at: string;
  error_message: string | null;
}

type TabType = 'keys' | 'docs' | 'get-docs';

export function SettingsDialog() {
  const isOpenStore = useUIStore((s) => s.settingsDialogOpen);
  const onCloseStore = useUIStore((s) => s.closeSettings);
  const defaultTabStore = useUIStore((s) => s.settingsDialogTab);

  const isOpen = isOpenStore;
  const onClose = onCloseStore;
  const defaultTab = defaultTabStore;

  const [activeTab, setActiveTab] = useState<TabType>(defaultTab);

  useEffect(() => {
    if (isOpen) {
      setActiveTab(defaultTab);
    }
  }, [defaultTab, isOpen]);

  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [keyProvider, setKeyProvider] = useState('openai');
  const [apiKeyVal, setApiKeyVal] = useState('');
  const [keyError, setKeyError] = useState<string | null>(null);

  const [docs, setDocs] = useState<DocumentData[]>([]);
  const [nextDocsCursor, setNextDocsCursor] = useState<string | null>(null);
  const [docLang, setDocLang] = useState('english');
  const [pasteContent, setPasteContent] = useState('');
  const [pasteFilename, setPasteFilename] = useState('');
  const [pasteType, setPasteType] = useState<'text/plain' | 'text/markdown'>('text/markdown');
  const [docError, setDocError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [savingPaste, setSavingPaste] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [jobs, setJobs] = useState<GetDocsJobData[]>([]);
  const [nextJobsCursor, setNextJobsCursor] = useState<string | null>(null);
  const [scraperUrl, setScraperUrl] = useState('');
  const [scraperRepo, setScraperRepo] = useState('');
  const [scraperLang, setScraperLang] = useState('english');
  const [scraperMaxPages, setScraperMaxPages] = useState(150);
  const [scraperMaxDepth, setScraperMaxDepth] = useState(3);
  const [scraperError, setScraperError] = useState<string | null>(null);
  const [scraperSubmitting, setScraperSubmitting] = useState(false);

  const loadKeys = useCallback(async () => {
    try {
      const data = await api.get<ApiKey[]>('/keys/');
      setKeys(data);
    } catch (err) {
      console.error('Failed to load API keys:', err);
    }
  }, []);

  const loadDocs = useCallback(async () => {
    try {
      const data = await api.get<CursorPaginated<DocumentData>>('/documents/');
      setDocs(data.results || []);
      setNextDocsCursor(data.next || null);
    } catch (err) {
      console.error('Failed to load documents:', err);
    }
  }, []);

  const isLoadingMoreDocsRef = useRef(false);

  const loadMoreDocs = useCallback(async () => {
    if (isLoadingMoreDocsRef.current || !nextDocsCursor) return;
    isLoadingMoreDocsRef.current = true;
    try {
      const data = await api.get<CursorPaginated<DocumentData>>(nextDocsCursor);
      setDocs((prev) => {
        const existingIds = new Set(prev.map((d) => d.id));
        const newDocs = (data.results || []).filter((d) => !existingIds.has(d.id));
        return [...prev, ...newDocs];
      });
      setNextDocsCursor(data.next || null);
    } catch (err) {
      console.error('Failed to load more documents:', err);
    } finally {
      isLoadingMoreDocsRef.current = false;
    }
  }, [nextDocsCursor]);

  const loadJobs = useCallback(async () => {
    try {
      const data = await api.get<CursorPaginated<GetDocsJobData>>('/getdocs-jobs/');
      setJobs(data.results || []);
      setNextJobsCursor(data.next || null);
    } catch (err) {
      console.error('Failed to load scraper jobs:', err);
    }
  }, []);

  const isLoadingMoreJobsRef = useRef(false);

  const loadMoreJobs = useCallback(async () => {
    if (isLoadingMoreJobsRef.current || !nextJobsCursor) return;
    isLoadingMoreJobsRef.current = true;
    try {
      const data = await api.get<CursorPaginated<GetDocsJobData>>(nextJobsCursor);
      setJobs((prev) => {
        const existingIds = new Set(prev.map((j) => j.id));
        const newJobs = (data.results || []).filter((j) => !existingIds.has(j.id));
        return [...prev, ...newJobs];
      });
      setNextJobsCursor(data.next || null);
    } catch (err) {
      console.error('Failed to load more scraper jobs:', err);
    } finally {
      isLoadingMoreJobsRef.current = false;
    }
  }, [nextJobsCursor]);

  const fetchTabData = useCallback(
    (tab: TabType) => {
      if (!auth.isAuthenticated()) return;

      if (tab === 'keys') {
        loadKeys();
      } else if (tab === 'docs') {
        loadDocs();
      } else if (tab === 'get-docs') {
        loadJobs();
      }
    },
    [loadKeys, loadDocs, loadJobs]
  );

  useEffect(() => {
    if (isOpen) {
      fetchTabData(activeTab);
    }
  }, [activeTab, isOpen, fetchTabData]);

  useEffect(() => {
    if (!isOpen || activeTab !== 'get-docs') return;

    const hasActiveJobs = jobs.some((j) => j.status === 'pending' || j.status === 'in_progress');
    if (!hasActiveJobs) return;

    const interval = setInterval(() => {
      loadJobs();
    }, 4000);

    return () => clearInterval(interval);
  }, [jobs, isOpen, activeTab, loadJobs]);

  useEffect(() => {
    if (!isOpen || activeTab !== 'docs') return;

    const hasActiveDocs = docs.some((d) => d.status === 'pending' || d.status === 'in_progress');
    if (!hasActiveDocs) return;

    const interval = setInterval(() => {
      loadDocs();
    }, 4000);

    return () => clearInterval(interval);
  }, [docs, isOpen, activeTab, loadDocs]);

  const handleAddKey = async (e: SubmitEvent) => {
    e.preventDefault();
    setKeyError(null);
    if (!apiKeyVal.trim()) return;

    try {
      await api.post('/keys/', {
        provider: keyProvider,
        api_key: apiKeyVal.trim(),
      });
      setApiKeyVal('');
      loadKeys();
    } catch (err: unknown) {
      setKeyError(err instanceof Error ? err.message : 'Failed to save API key.');
    }
  };

  const handleDeleteKey = async (id: string) => {
    try {
      await api.delete(`/keys/${id}/`);
      loadKeys();
    } catch {
      setKeyError('Failed to delete API key.');
    }
  };

  const handleFileUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.currentTarget.files?.[0];
    if (!file) return;

    setDocError(null);
    setUploading(true);

    const formData = new FormData();
    formData.append('file', file);
    formData.append('language', docLang);

    try {
      await api.post('/documents/', formData);
      loadDocs();
    } catch (err: unknown) {
      setDocError(err instanceof Error ? err.message : 'Failed to upload document.');
    } finally {
      setUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handlePasteText = async (e: SubmitEvent) => {
    e.preventDefault();
    setDocError(null);
    if (!pasteContent.trim()) return;
    setSavingPaste(true);

    let filename = pasteFilename.trim();
    const isMarkdown = pasteType === 'text/markdown';
    const extension = isMarkdown ? '.md' : '.txt';

    if (!filename) {
      const pad = (n: number) => String(n).padStart(2, '0');
      const now = new Date();
      const timestamp = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}_${pad(
        now.getHours()
      )}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`;
      filename = `pasted_${timestamp}${extension}`;
    } else {
      filename = filename.replace(/\.(txt|md|markdown)$/i, '');
      filename = `${filename}${extension}`;
    }

    try {
      await api.post('/documents/', {
        content: pasteContent,
        content_type: pasteType,
        filename: filename,
        language: docLang,
      });
      setPasteContent('');
      setPasteFilename('');
      loadDocs();
    } catch (err: unknown) {
      setDocError(err instanceof Error ? err.message : 'Failed to process pasted text.');
    } finally {
      setSavingPaste(false);
    }
  };

  const handleDeleteDoc = async (id: string) => {
    try {
      await api.delete(`/documents/${id}/`);
      loadDocs();
    } catch {
      setDocError('Failed to delete document.');
    }
  };

  const handleCreateScraperJob = async (e: SubmitEvent) => {
    e.preventDefault();
    setScraperError(null);

    const url = scraperUrl.trim();
    const repo = scraperRepo.trim();

    if (!url && !repo) {
      setScraperError('Specify either a web URL or a GitHub Repository.');
      return;
    }

    setScraperSubmitting(true);

    try {
      await api.post('/getdocs-jobs/', {
        url: url || undefined,
        github_repo: repo || undefined,
        language: scraperLang,
        max_pages: scraperMaxPages,
        max_depth: scraperMaxDepth,
      });

      setScraperUrl('');
      setScraperRepo('');
      loadJobs();
    } catch (err: unknown) {
      setScraperError(err instanceof Error ? err.message : 'Failed to start crawling job.');
    } finally {
      setScraperSubmitting(false);
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} id="settings-popover" className="settings-dialog">
      <div className="settings-dialog-wrapper">
        <aside className="settings-dialog-sidebar">
          <div className="settings-dialog-sidebar-header">
            <h2>Settings</h2>
          </div>
          <nav className="settings-dialog-tabs">
            <button
              type="button"
              className={`settings-dialog-tab-btn ${activeTab === 'keys' ? 'active' : ''}`}
              onClick={() => setActiveTab('keys')}
            >
              <Icon name="pencil" size={16} />
              API Keys
            </button>
            <button
              type="button"
              className={`settings-dialog-tab-btn ${activeTab === 'docs' ? 'active' : ''}`}
              onClick={() => setActiveTab('docs')}
            >
              <Icon name="file" size={16} />
              Documents
            </button>
            <button
              type="button"
              className={`settings-dialog-tab-btn ${activeTab === 'get-docs' ? 'active' : ''}`}
              onClick={() => setActiveTab('get-docs')}
            >
              <Icon name="search" size={16} />
              Get Docs
            </button>
          </nav>
          <div className="settings-dialog-sidebar-footer">
            <button type="button" className="settings-dialog-close" onClick={onClose}>
              <Icon name="x" size={14} /> Close
            </button>
          </div>
        </aside>

        <main className="settings-dialog-content">
          {activeTab === 'keys' && (
            <div className="settings-section">
              <h3>API Keys</h3>
              {keyError && <div className="error-banner">{keyError}</div>}

              <form className="settings-form-row" onSubmit={handleAddKey}>
                <div className="form-field">
                  <label htmlFor="key-provider">Provider</label>
                  <CustomDropdown
                    value={keyProvider}
                    options={['openai', 'openrouter', 'gemini', 'github']}
                    onChange={setKeyProvider}
                    labelFormatter={formatProviderName}
                    variant="form"
                  />
                </div>
                <div className="form-field flex-grow">
                  <label htmlFor="key-value">API Key</label>
                  <input
                    id="key-value"
                    type="password"
                    value={apiKeyVal}
                    onChange={(e) => setApiKeyVal(e.target.value)}
                    placeholder="Enter your API key"
                    required
                  />
                </div>
                <button type="submit" className="btn-primary settings-btn-primary-height">
                  Save
                </button>
              </form>

              <div className="settings-list-container">
                <h4>Configured Keys</h4>
                {keys.length === 0 ? (
                  <p className="settings-empty">
                    No keys configured yet. The app will fall back to local model if available.
                  </p>
                ) : (
                  <ul className="settings-list">
                    {keys.map((k) => (
                      <li key={k.id} className="settings-list-item">
                        <div>
                          <strong>{formatProviderName(k.provider)}</strong>
                          <span className="settings-subtext">{k.masked_key}</span>
                        </div>
                        <button
                          type="button"
                          className="settings-action-icon-btn danger"
                          onClick={() => handleDeleteKey(k.id)}
                          aria-label="Delete key"
                        >
                          <Icon name="trash" size={14} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}

          {activeTab === 'docs' && (
            <div className="settings-section">
              <h3>Documents</h3>
              {docError && <div className="error-banner">{docError}</div>}

              <div className="form-field" style={{ marginBottom: 'var(--spacing-4)' }}>
                <label htmlFor="doc-lang-select">Document Language</label>
                <div style={{ maxWidth: '200px' }}>
                  <CustomDropdown
                    value={docLang}
                    options={['english', 'polish']}
                    onChange={setDocLang}
                    labelFormatter={formatCapitalized}
                    variant="form"
                  />
                </div>
                <span className="settings-subtext" style={{ marginTop: '4px' }}>
                  Applies to both uploaded files and pasted text. Used for search indexing and
                  keyword lemmatization.
                </span>
              </div>

              <div
                style={{
                  borderBottom: '1px solid var(--color-border)',
                  marginBottom: 'var(--spacing-4)',
                }}
              />

              <div
                className="settings-upload-section"
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 'var(--spacing-2)',
                  marginBottom: 'var(--spacing-4)',
                }}
              >
                <h4>Upload File</h4>
                <div>
                  <input
                    ref={fileInputRef}
                    id="doc-file-upload"
                    type="file"
                    accept=".pdf,.txt,.md,.docx"
                    style={{ display: 'none' }}
                    onChange={handleFileUpload}
                  />
                  <button
                    type="button"
                    className="btn-primary settings-btn-primary-height"
                    disabled={uploading}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    {uploading ? 'Uploading...' : 'Upload File'}
                  </button>
                </div>
              </div>

              <div
                style={{
                  borderBottom: '1px solid var(--color-border)',
                  marginBottom: 'var(--spacing-4)',
                }}
              />

              <form className="settings-paste-form" onSubmit={handlePasteText}>
                <h4>Paste Text Document</h4>
                <div className="settings-form-row">
                  <div className="form-field flex-grow">
                    <label htmlFor="paste-filename">Filename</label>
                    <input
                      id="paste-filename"
                      type="text"
                      value={pasteFilename}
                      onChange={(e) => setPasteFilename(e.target.value)}
                      placeholder="untitled"
                      disabled={savingPaste}
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor="paste-type">Format</label>
                    <select
                      id="paste-type"
                      value={pasteType}
                      onChange={(e) =>
                        setPasteType(e.target.value as 'text/plain' | 'text/markdown')
                      }
                      disabled={savingPaste}
                    >
                      <option value="text/plain">Plain Text (.txt)</option>
                      <option value="text/markdown">Markdown (.md)</option>
                    </select>
                  </div>
                </div>
                <div className="form-field">
                  <label htmlFor="paste-content">Content</label>
                  <textarea
                    id="paste-content"
                    value={pasteContent}
                    onChange={(e) => setPasteContent(e.target.value)}
                    placeholder="Paste text contents here..."
                    rows={4}
                    required
                    disabled={savingPaste}
                  />
                </div>
                <button
                  type="submit"
                  className="btn-primary"
                  disabled={!pasteContent.trim() || savingPaste}
                >
                  {savingPaste ? 'Saving and Indexing...' : 'Save Paste'}
                </button>
              </form>

              <div className="settings-list-container">
                <h4>Indexed Documents</h4>
                {docs.length === 0 ? (
                  <p className="settings-empty">No documents uploaded yet.</p>
                ) : (
                  <ul
                    className="settings-list max-height-list"
                    onScroll={(e) => {
                      const target = e.currentTarget;
                      if (target.scrollHeight - target.scrollTop - target.clientHeight <= 30) {
                        loadMoreDocs();
                      }
                    }}
                  >
                    {docs.map((d) => {
                      const isProcessing = d.status === 'pending' || d.status === 'in_progress';
                      return (
                        <li key={d.id} className="settings-list-item-block">
                          <div className="job-item-header">
                            <strong className="job-target" title={d.filename}>
                              {d.filename}
                            </strong>
                            <div className="job-actions-wrap">
                              {d.status && d.status !== 'completed' && (
                                <span className={`job-status-badge ${d.status}`}>
                                  {d.status.replace('_', ' ')}
                                </span>
                              )}
                              {!isProcessing && (
                                <button
                                  type="button"
                                  className="settings-action-icon-btn danger"
                                  onClick={() => handleDeleteDoc(d.id)}
                                  aria-label="Delete document"
                                >
                                  <Icon name="trash" size={14} />
                                </button>
                              )}
                            </div>
                          </div>
                          <div className="job-item-details">
                            <span>
                              {d.content_type} • {d.language}
                            </span>
                          </div>
                          {d.error_message && (
                            <div className="job-item-error">Error: {d.error_message}</div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          )}

          {activeTab === 'get-docs' && (
            <div className="settings-section">
              <h3>Get Docs</h3>
              {scraperError && <div className="error-banner">{scraperError}</div>}

              <form className="settings-scraper-form" onSubmit={handleCreateScraperJob}>
                <div className="form-field">
                  <label htmlFor="scraper-url">Target URL</label>
                  <input
                    id="scraper-url"
                    type="url"
                    value={scraperUrl}
                    onChange={(e) => setScraperUrl(e.target.value)}
                    placeholder="https://docs.example.com/"
                  />
                </div>

                <div className="form-field">
                  <label htmlFor="scraper-repo">Or GitHub Repository</label>
                  <input
                    id="scraper-repo"
                    type="text"
                    value={scraperRepo}
                    onChange={(e) => setScraperRepo(e.target.value)}
                    placeholder="https://github.com/owner/repository"
                  />
                </div>

                <div className="settings-grid">
                  <div className="form-field">
                    <label htmlFor="scraper-lang">Language</label>
                    <CustomDropdown
                      value={scraperLang}
                      options={['english', 'polish']}
                      onChange={setScraperLang}
                      labelFormatter={formatCapitalized}
                      variant="form"
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor="scraper-pages">Max Pages</label>
                    <input
                      id="scraper-pages"
                      type="number"
                      value={scraperMaxPages}
                      onChange={(e) => setScraperMaxPages(Number(e.target.value))}
                      min={1}
                      max={1000}
                    />
                  </div>
                  <div className="form-field">
                    <label htmlFor="scraper-depth">Max Depth</label>
                    <input
                      id="scraper-depth"
                      type="number"
                      value={scraperMaxDepth}
                      onChange={(e) => setScraperMaxDepth(Number(e.target.value))}
                      min={1}
                      max={10}
                    />
                  </div>
                </div>

                <button
                  type="submit"
                  className="btn-primary settings-btn-primary-height"
                  disabled={scraperSubmitting}
                >
                  {scraperSubmitting ? 'Submitting...' : 'Trigger Get Docs Job'}
                </button>
              </form>

              <div className="settings-list-container">
                <h4>Recent Jobs</h4>
                {jobs.length === 0 ? (
                  <p className="settings-empty">No scraping jobs run yet.</p>
                ) : (
                  <ul
                    className="settings-list max-height-list"
                    onScroll={(e) => {
                      const target = e.currentTarget;
                      if (target.scrollHeight - target.scrollTop - target.clientHeight <= 30) {
                        loadMoreJobs();
                      }
                    }}
                  >
                    {jobs.map((j) => (
                      <li key={j.id} className="settings-list-item-block">
                        <div className="job-item-header">
                          <span className="job-target">{j.url || j.github_repo}</span>
                          <span className={`job-status-badge ${j.status}`}>
                            {j.status.replace('_', ' ')}
                          </span>
                        </div>
                        <div className="job-item-details">
                          <span>
                            Pages: {j.pages_fetched} {j.pages_total ? `/ ${j.pages_total}` : ''}
                          </span>
                          <span>Language: {formatCapitalized(j.language)}</span>
                        </div>
                        {j.error_message && (
                          <div className="job-item-error">Error: {j.error_message}</div>
                        )}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          )}
        </main>
      </div>
    </Modal>
  );
}
