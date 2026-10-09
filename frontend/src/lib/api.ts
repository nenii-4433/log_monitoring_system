import { apiBaseUrl } from "./supabase";

export interface Organization {
  id: string;
  name: string;
  role: "owner" | "member";
}

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
}

export interface LogEntry {
  id: string;
  timestamp: string;
  received_at: string;
  severity: "trace" | "debug" | "info" | "warning" | "error" | "critical" | null;
  source_severity: "trace" | "debug" | "info" | "warning" | "error" | "critical" | null;
  prediction_status: "pending" | "complete" | "failed";
  prediction_confidence: number | null;
  prediction_reason: string | null;
  prediction_method: string | null;
  prediction_error: string | null;
  service: string;
  environment: string | null;
  message: string;
  attributes: Record<string, unknown> | null;
}

export interface ServiceCriticality {
  service: string;
  criticality: "low" | "normal" | "high" | "critical";
  updated_at?: string;
}

export interface LogSearchResponse {
  items: LogEntry[];
  next_cursor: string | null;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiRequest<T>(
  path: string,
  accessToken: string,
  options: RequestOptions = {},
): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: options.method ?? "GET",
    headers: {
      Authorization: `Bearer ${accessToken}`,
      ...(options.body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const errorBody: unknown = await response.json();
      if (
        typeof errorBody === "object" &&
        errorBody !== null &&
        "detail" in errorBody &&
        typeof errorBody.detail === "string"
      ) {
        message = errorBody.detail;
      } else if (
        typeof errorBody === "object" &&
        errorBody !== null &&
        "error" in errorBody &&
        typeof errorBody.error === "object" &&
        errorBody.error !== null &&
        "message" in errorBody.error &&
        typeof errorBody.error.message === "string"
      ) {
        message = errorBody.error.message;
      }
    } catch {
      message = `Request failed (${response.status})`;
    }
    throw new Error(message);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}
