import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import type { Session } from "@supabase/supabase-js";

import {
  apiRequest,
  type ApiKey,
  type LogEntry,
  type LogSearchResponse,
  type Organization,
} from "./lib/api";
import { supabase } from "./lib/supabase";

const severities = ["trace", "debug", "info", "warning", "error", "critical"] as const;

function formatDate(value: string | null): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function toIsoOrEmpty(value: string): string {
  return value ? new Date(value).toISOString() : "";
}

function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [authError, setAuthError] = useState("");

  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [selectedOrganizationId, setSelectedOrganizationId] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [organizationLoading, setOrganizationLoading] = useState(false);
  const [showOrganizationForm, setShowOrganizationForm] = useState(false);

  const [apiKeys, setApiKeys] = useState<ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState("");
  const [oneTimeKey, setOneTimeKey] = useState("");
  const [keyLoading, setKeyLoading] = useState(false);

  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [logService, setLogService] = useState("");
  const [logEnvironment, setLogEnvironment] = useState("");
  const [logSeverity, setLogSeverity] = useState("");
  const [logFrom, setLogFrom] = useState("");
  const [logTo, setLogTo] = useState("");
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [activeCursor, setActiveCursor] = useState<string | null>(null);
  const [logsLoading, setLogsLoading] = useState(false);
  const searchInFlight = useRef(false);

  const [pageError, setPageError] = useState("");
  const [pageNotice, setPageNotice] = useState("");

  useEffect(() => {
    if (!supabase) {
      setAuthLoading(false);
      return;
    }

    let alive = true;
    void supabase.auth.getSession().then(({ data, error }) => {
      if (!alive) return;
      if (error) setAuthError(error.message);
      setSession(data.session);
      setAuthLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, updatedSession) => {
      setSession(updatedSession);
      setAuthError("");
      setAuthNotice("");
    });

    return () => {
      alive = false;
      subscription.unsubscribe();
    };
  }, []);

  const accessToken = session?.access_token ?? "";
  const selectedOrganization = useMemo(
    () => organizations.find((organization) => organization.id === selectedOrganizationId) ?? null,
    [organizations, selectedOrganizationId],
  );

  const loadOrganizations = useCallback(async () => {
    if (!accessToken) return;
    const result = await apiRequest<{ items: Organization[] }>(
      "/v1/organizations",
      accessToken,
    );
    setOrganizations(result.items);
    setSelectedOrganizationId((current) => {
      if (result.items.some((organization) => organization.id === current)) {
        return current;
      }
      return result.items[0]?.id ?? "";
    });
  }, [accessToken]);

  useEffect(() => {
    if (!accessToken) {
      setOrganizations([]);
      setSelectedOrganizationId("");
      return;
    }
    void loadOrganizations().catch((error: unknown) => {
      setPageError(error instanceof Error ? error.message : "Could not load organizations.");
    });
  }, [accessToken, loadOrganizations]);

  const loadApiKeys = useCallback(async () => {
    if (!accessToken || !selectedOrganization || selectedOrganization.role !== "owner") {
      setApiKeys([]);
      return;
    }
    const result = await apiRequest<{ items: ApiKey[] }>(
      `/v1/organizations/${selectedOrganization.id}/api-keys`,
      accessToken,
    );
    setApiKeys(result.items);
  }, [accessToken, selectedOrganization]);

  useEffect(() => {
    setOneTimeKey("");
    if (!selectedOrganization || !accessToken) {
      setApiKeys([]);
      return;
    }
    if (selectedOrganization.role !== "owner") {
      setApiKeys([]);
      return;
    }
    void loadApiKeys().catch((error: unknown) => {
      setPageError(error instanceof Error ? error.message : "Could not load API keys.");
    });
  }, [accessToken, loadApiKeys, selectedOrganization]);

  const searchLogs = useCallback(
    async (cursor: string | null = null, quiet = false) => {
      if (!accessToken || !selectedOrganization || searchInFlight.current) return;
      searchInFlight.current = true;
      if (!quiet) {
        setLogsLoading(true);
        setPageError("");
      }
      const params = new URLSearchParams({
        organization_id: selectedOrganization.id,
        limit: "50",
      });
      const from = toIsoOrEmpty(logFrom);
      const to = toIsoOrEmpty(logTo);
      if (from) params.set("from", from);
      if (to) params.set("to", to);
      if (logSeverity) params.append("severity", logSeverity);
      if (logService.trim()) params.set("service", logService.trim());
      if (logEnvironment.trim()) params.set("environment", logEnvironment.trim());
      if (cursor) params.set("cursor", cursor);

      try {
        const result = await apiRequest<LogSearchResponse>(
          `/v1/logs?${params.toString()}`,
          accessToken,
        );
        setLogs(result.items);
        setNextCursor(result.next_cursor);
        setActiveCursor(cursor);
        if (quiet) setPageError("");
      } catch (error) {
        setPageError(error instanceof Error ? error.message : "Could not load logs.");
      } finally {
        searchInFlight.current = false;
        if (!quiet) setLogsLoading(false);
      }
    },
    [
      accessToken,
      logEnvironment,
      logFrom,
      logService,
      logSeverity,
      logTo,
      selectedOrganization,
    ],
  );

  useEffect(() => {
    setLogs([]);
    setNextCursor(null);
    setActiveCursor(null);
    if (selectedOrganization) void searchLogs(null);
  }, [selectedOrganizationId]);

  useEffect(() => {
    if (!accessToken || !selectedOrganization || activeCursor !== null) return;

    const intervalId = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void searchLogs(null, true);
      }
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [accessToken, activeCursor, searchLogs, selectedOrganization]);

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) return;
    setAuthError("");
    setAuthNotice("");
    setAuthLoading(true);

    try {
      if (authMode === "signup") {
        const { data, error } = await supabase.auth.signUp({
          email: authEmail.trim(),
          password: authPassword,
        });
        if (error) throw error;
        if (data.session) {
          setSession(data.session);
        } else {
          setAuthNotice("Check your email to confirm your account, then sign in.");
          setAuthMode("signin");
        }
      } else {
        const { data, error } = await supabase.auth.signInWithPassword({
          email: authEmail.trim(),
          password: authPassword,
        });
        if (error) throw error;
        setSession(data.session);
      }
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Authentication failed.");
    } finally {
      setAuthLoading(false);
    }
  }

  async function handleSignOut() {
    if (!supabase) return;
    try {
      const { error } = await supabase.auth.signOut();
      if (error) setAuthError(error.message);
      else setAuthError("");
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : "Could not sign out.");
    } finally {
      setSession(null);
      setOrganizations([]);
      setSelectedOrganizationId("");
      setApiKeys([]);
      setLogs([]);
      setOneTimeKey("");
      setPageError("");
      setPageNotice("");
    }
  }

  async function handleCreateOrganization(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken) return;
    setOrganizationLoading(true);
    setPageError("");
    try {
      const organization = await apiRequest<Organization>("/v1/organizations", accessToken, {
        method: "POST",
        body: { name: organizationName.trim() },
      });
      setOrganizationName("");
      await loadOrganizations();
      setSelectedOrganizationId(organization.id);
      setShowOrganizationForm(false);
      setPageNotice("Organization created.");
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Could not create organization.");
    } finally {
      setOrganizationLoading(false);
    }
  }

  async function handleCreateApiKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!accessToken || !selectedOrganization) return;
    setKeyLoading(true);
    setPageError("");
    setOneTimeKey("");
    try {
      const result = await apiRequest<{ id: string; name: string; key: string }>(
        `/v1/organizations/${selectedOrganization.id}/api-keys`,
        accessToken,
        { method: "POST", body: { name: newKeyName.trim() } },
      );
      setOneTimeKey(result.key);
      setNewKeyName("");
      await loadApiKeys();
      setPageNotice("API key created. Copy it now; it will only be shown once.");
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Could not create API key.");
    } finally {
      setKeyLoading(false);
    }
  }

  async function handleRevokeApiKey(key: ApiKey) {
    if (!accessToken || !selectedOrganization) return;
    if (!window.confirm(`Revoke the key "${key.name}"? It will stop working immediately.`)) {
      return;
    }
    setPageError("");
    try {
      await apiRequest<void>(
        `/v1/organizations/${selectedOrganization.id}/api-keys/${key.id}`,
        accessToken,
        { method: "DELETE" },
      );
      await loadApiKeys();
      setPageNotice(`API key "${key.name}" revoked.`);
    } catch (error) {
      setPageError(error instanceof Error ? error.message : "Could not revoke API key.");
    }
  }

  if (!supabase) {
    return (
      <main className="setup-screen">
        <div className="setup-card">
          <span className="brand-mark">S</span>
          <p className="eyebrow">LOCAL SETUP</p>
          <h1>Connect your Supabase project</h1>
          <p>
            Copy <code>frontend\.env.example</code> to <code>frontend\.env</code> and set
            your local Supabase URL and <strong>Publishable</strong> key. Never put
            the Supabase Secret key in this frontend configuration.
          </p>
          <p className="muted">Restart the Vite development server after saving the file.</p>
        </div>
      </main>
    );
  }

  if (authLoading) {
    return (
      <main className="loading-screen">
        <span className="spinner" />
        <span>Connecting to your workspace…</span>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="auth-screen">
        <section className="auth-visual">
          <div className="brand-lockup">
            <span className="brand-mark">S</span>
            <span>signal<span className="brand-period">.</span></span>
          </div>
          <div className="visual-content">
            <p className="eyebrow">LOG INTELLIGENCE, WITHOUT THE NOISE</p>
            <h1>Find the signal<br />inside every incident.</h1>
            <p className="visual-copy">
              Bring your application logs together, search across services, and keep
              every organization’s data private by design.
            </p>
            <div className="signal-visual" aria-hidden="true">
              <span /><span /><span /><span /><span /><span /><span /><span /><span />
            </div>
          </div>
          <p className="visual-footer">BUILT FOR TEAMS THAT SHIP</p>
        </section>
        <section className="auth-panel">
          <div className="auth-box">
            <p className="eyebrow">{authMode === "signin" ? "WELCOME BACK" : "GET STARTED"}</p>
            <h2>{authMode === "signin" ? "Sign in to Signal" : "Create your account"}</h2>
            <p className="muted">
              {authMode === "signin"
                ? "Your logs are waiting where you left them."
                : "Start your organization’s private log workspace."}
            </p>
            {authError && <div className="notice notice-error" role="alert">{authError}</div>}
            {authNotice && <div className="notice notice-success" role="status">{authNotice}</div>}
            <form className="form-stack" onSubmit={handleAuthSubmit}>
              <label>
                Email address
                <input
                  type="email"
                  autoComplete="email"
                  required
                  value={authEmail}
                  onChange={(event) => setAuthEmail(event.target.value)}
                  placeholder="you@company.com"
                />
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete={authMode === "signin" ? "current-password" : "new-password"}
                  minLength={8}
                  required
                  value={authPassword}
                  onChange={(event) => setAuthPassword(event.target.value)}
                  placeholder="At least 8 characters"
                />
              </label>
              <button className="button button-primary button-wide" disabled={authLoading}>
                {authLoading
                  ? "Please wait…"
                  : authMode === "signin"
                    ? "Sign in"
                    : "Create account"}
                {!authLoading && <span aria-hidden="true">↗</span>}
              </button>
            </form>
            <p className="auth-switch">
              {authMode === "signin" ? "New to Signal?" : "Already have an account?"}{" "}
              <button
                className="text-button"
                onClick={() => {
                  setAuthMode(authMode === "signin" ? "signup" : "signin");
                  setAuthError("");
                  setAuthNotice("");
                }}
              >
                {authMode === "signin" ? "Create an account" : "Sign in"}
              </button>
            </p>
            <p className="auth-legal">By continuing, you agree to keep your workspace credentials secure.</p>
          </div>
        </section>
      </main>
    );
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand-lockup" href="#top" aria-label="Signal dashboard">
          <span className="brand-mark">S</span>
          <span>signal<span className="brand-period">.</span></span>
        </a>
        <div className="workspace-label">WORKSPACE</div>
        <label className="organization-picker">
          <span className="sr-only">Select organization</span>
          <select
            value={selectedOrganizationId}
            onChange={(event) => setSelectedOrganizationId(event.target.value)}
            disabled={organizations.length === 0}
          >
            {organizations.length === 0 && <option value="">No organization yet</option>}
            {organizations.map((organization) => (
              <option value={organization.id} key={organization.id}>{organization.name}</option>
            ))}
          </select>
        </label>
        {organizations.length > 0 && (
          <>
            <button
              className="add-organization-button"
              type="button"
              onClick={() => {
                setShowOrganizationForm((showing) => !showing);
                setOrganizationName("");
                setPageError("");
              }}
            >
              <span aria-hidden="true">＋</span> Add organization
            </button>
            {showOrganizationForm && (
              <form
                className="organization-create-panel"
                onSubmit={(event) => void handleCreateOrganization(event)}
              >
                <label className="sr-only" htmlFor="new-organization-name">
                  New organization name
                </label>
                <input
                  id="new-organization-name"
                  autoFocus
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  maxLength={120}
                  required
                  placeholder="Organization name"
                />
                <div className="organization-create-actions">
                  <button
                    className="button button-primary"
                    disabled={organizationLoading}
                  >
                    {organizationLoading ? "Creating…" : "Create"}
                  </button>
                  <button
                    className="button button-secondary"
                    type="button"
                    disabled={organizationLoading}
                    onClick={() => {
                      setShowOrganizationForm(false);
                      setOrganizationName("");
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </>
        )}
        <nav className="side-nav" aria-label="Main navigation">
          <a className="nav-item nav-item-active" href="#logs"><span>◫</span> Log explorer</a>
          <a className="nav-item" href="#keys"><span>⌘</span> API keys</a>
        </nav>
        <div className="sidebar-bottom">
          <div className="pilot-badge"><span className="status-dot" /> Pilot workspace</div>
          <div className="user-card">
            <span className="avatar">{session.user.email?.slice(0, 1).toUpperCase() ?? "U"}</span>
            <span className="user-email">{session.user.email}</span>
            <button className="icon-button" title="Sign out" onClick={() => void handleSignOut()}>↗</button>
          </div>
        </div>
      </aside>

      <main className="main-content" id="top">
        <header className="topbar">
          <div>
            <p className="breadcrumb">WORKSPACE <span>/</span> OVERVIEW</p>
            <h1>Log explorer</h1>
          </div>
          <div className="topbar-status"><span className="status-dot" /> API connected locally</div>
        </header>

        <div className="content-wrap">
          {pageError && <div className="notice notice-error" role="alert">{pageError}<button onClick={() => setPageError("")}>Dismiss</button></div>}
          {pageNotice && <div className="notice notice-success" role="status">{pageNotice}<button onClick={() => setPageNotice("")}>Dismiss</button></div>}

          {organizations.length === 0 ? (
            <section className="empty-organization">
              <div className="empty-icon">＋</div>
              <p className="eyebrow">YOUR WORKSPACE STARTS HERE</p>
              <h2>Create your first organization</h2>
              <p className="muted">Organizations keep team membership, API keys, and logs isolated.</p>
              <form className="inline-create-form" onSubmit={(event) => void handleCreateOrganization(event)}>
                <label className="sr-only" htmlFor="organization-name">Organization name</label>
                <input
                  id="organization-name"
                  value={organizationName}
                  onChange={(event) => setOrganizationName(event.target.value)}
                  maxLength={120}
                  required
                  placeholder="e.g. Acme Engineering"
                />
                <button className="button button-primary" disabled={organizationLoading}>
                  {organizationLoading ? "Creating…" : "Create organization"}
                </button>
              </form>
            </section>
          ) : (
            <>
              <section className="welcome-row">
                <div>
                  <p className="eyebrow">YOUR OBSERVABILITY WORKSPACE</p>
                  <h2>{selectedOrganization?.name ?? "Loading organization"}</h2>
                  <p className="muted">Search, filter, and investigate application events.</p>
                </div>
                <span className="role-pill">{selectedOrganization?.role}</span>
              </section>

              <section className="filter-card" id="logs">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">DISCOVER WHAT’S HAPPENING</p>
                    <h2>Search logs</h2>
                  </div>
                  <div className="result-meta">
                    <span className="live-status" title="The latest log results refresh every five seconds while this tab is visible.">
                      <span className="status-dot" />
                      {activeCursor === null ? "Auto-refresh · 5s" : "Auto-refresh paused"}
                    </span>
                    <span className="result-count">{logs.length} {logs.length === 1 ? "event" : "events"}</span>
                  </div>
                </div>
                <form
                  className="filter-grid"
                  onSubmit={(event) => {
                    event.preventDefault();
                    void searchLogs(null);
                  }}
                >
                  <label>
                    Severity
                    <select value={logSeverity} onChange={(event) => setLogSeverity(event.target.value)}>
                      <option value="">All severities</option>
                      {severities.map((value) => <option value={value} key={value}>{value}</option>)}
                    </select>
                  </label>
                  <label>
                    Service
                    <input value={logService} onChange={(event) => setLogService(event.target.value)} placeholder="Any service" maxLength={120} />
                  </label>
                  <label>
                    Environment
                    <input value={logEnvironment} onChange={(event) => setLogEnvironment(event.target.value)} placeholder="Any environment" maxLength={120} />
                  </label>
                  <label>
                    From
                    <input type="datetime-local" value={logFrom} onChange={(event) => setLogFrom(event.target.value)} />
                  </label>
                  <label>
                    To
                    <input type="datetime-local" value={logTo} onChange={(event) => setLogTo(event.target.value)} />
                  </label>
                  <button className="button button-primary filter-submit" disabled={logsLoading}>
                    {logsLoading ? "Searching…" : "Search logs"}
                  </button>
                </form>
              </section>

              <section className="logs-card">
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Timestamp</th>
                        <th>Service</th>
                        <th>Environment</th>
                        <th>Message</th>
                      </tr>
                    </thead>
                    <tbody>
                      {logs.map((log) => (
                        <tr key={log.id}>
                          <td><span className={`severity severity-${log.severity}`}>{log.severity}</span></td>
                          <td className="timestamp-cell">{formatDate(log.timestamp)}</td>
                          <td className="service-cell">{log.service}</td>
                          <td>{log.environment ?? "—"}</td>
                          <td className="message-cell">
                            <span>{log.message}</span>
                            {log.attributes && Object.keys(log.attributes).length > 0 && (
                              <details>
                                <summary>attributes</summary>
                                <pre>{JSON.stringify(log.attributes, null, 2)}</pre>
                              </details>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {!logsLoading && logs.length === 0 && (
                    <div className="empty-logs">
                      <span className="empty-icon">⌕</span>
                      <strong>No log events found</strong>
                      <span>Try changing the filters or send a log from your application.</span>
                    </div>
                  )}
                </div>
                <footer className="table-footer">
                  <span>{logsLoading ? "Loading events…" : `Showing ${logs.length} events`}</span>
                  <div className="pagination-actions">
                    <button
                      className="button button-secondary"
                      disabled={!activeCursor || logsLoading}
                      onClick={() => void searchLogs(null)}
                    >
                      Newest
                    </button>
                    <button
                      className="button button-secondary"
                      disabled={!nextCursor || logsLoading}
                      onClick={() => void searchLogs(nextCursor)}
                    >
                      Older events <span aria-hidden="true">→</span>
                    </button>
                  </div>
                </footer>
              </section>

              <section className="keys-card" id="keys">
                <div className="section-heading">
                  <div>
                    <p className="eyebrow">SECURE INGESTION</p>
                    <h2>API keys</h2>
                  </div>
                  {selectedOrganization?.role === "owner" && (
                    <span className="muted small-copy">Secrets are shown once</span>
                  )}
                </div>
                {selectedOrganization?.role === "owner" ? (
                  <>
                    <form className="key-create-form" onSubmit={(event) => void handleCreateApiKey(event)}>
                      <label className="sr-only" htmlFor="key-name">Key name</label>
                      <input
                        id="key-name"
                        value={newKeyName}
                        onChange={(event) => setNewKeyName(event.target.value)}
                        maxLength={120}
                        required
                        placeholder="Name this key (e.g. Production collector)"
                      />
                      <button className="button button-primary" disabled={keyLoading}>
                        {keyLoading ? "Creating…" : "＋ Create API key"}
                      </button>
                    </form>
                    {oneTimeKey && (
                      <div className="one-time-key">
                        <div>
                          <strong>Copy this key now</strong>
                          <span>It won’t be displayed again.</span>
                        </div>
                        <code>{oneTimeKey}</code>
                        <button
                          className="button button-secondary"
                          onClick={() => void navigator.clipboard.writeText(oneTimeKey)}
                        >
                          Copy key
                        </button>
                      </div>
                    )}
                    <div className="key-list">
                      {apiKeys.map((key) => (
                        <div className="key-row" key={key.id}>
                          <span className={`key-state ${key.revoked_at ? "key-state-revoked" : ""}`} />
                          <div className="key-details">
                            <strong>{key.name}</strong>
                            <span><code>{key.key_prefix}••••••</code> · created {formatDate(key.created_at)}</span>
                          </div>
                          <span className="key-last-used">Last used {formatDate(key.last_used_at)}</span>
                          {key.revoked_at ? (
                            <span className="revoked-label">Revoked</span>
                          ) : (
                            <button className="text-button text-danger" onClick={() => void handleRevokeApiKey(key)}>
                              Revoke
                            </button>
                          )}
                        </div>
                      ))}
                      {apiKeys.length === 0 && <p className="muted empty-key-message">No API keys yet. Create one to connect a log source.</p>}
                    </div>
                  </>
                ) : (
                  <p className="muted">Only organization owners can view or manage API keys.</p>
                )}
              </section>
            </>
          )}
        </div>
      </main>
    </div>
  );
}

export default App;
