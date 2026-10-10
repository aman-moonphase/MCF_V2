// Turns FastAPI error bodies into messages a user can read.
//
// FastAPI returns `detail` either as a string (HTTPException) or, for request validation (422),
// as an array of { loc, msg, type } objects. Rendering that array directly produced "[object Object]".

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
  type?: string;
}

const FIELD_LABELS: Record<string, string> = {
  email: 'Email',
  password: 'Password',
  new_password: 'New password',
  title: 'Title',
  source_reference: 'Source',
};

function fieldName(loc?: (string | number)[]): string | undefined {
  const parts = (loc || []).filter((p) => p !== 'body' && p !== 'query' && p !== 'path');
  const last = parts[parts.length - 1];
  return typeof last === 'string' ? last : undefined;
}

function describeIssue(issue: ValidationIssue): string {
  const field = fieldName(issue.loc);
  const msg = (issue.msg || '').replace(/^Value error,\s*/i, '').trim();

  if (field === 'email' && /email/i.test(msg)) {
    return 'Please enter a valid email address.';
  }
  if (!msg) {
    return field ? `${FIELD_LABELS[field] || field} is invalid.` : 'Invalid request.';
  }
  const sentence = msg.charAt(0).toUpperCase() + msg.slice(1);
  return field ? `${FIELD_LABELS[field] || field}: ${sentence}` : sentence;
}

export function formatApiErrorDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string' && detail.trim()) {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => (typeof item === 'string' ? item : describeIssue(item as ValidationIssue)))
      .filter(Boolean);
    return messages.length ? Array.from(new Set(messages)).join(' ') : fallback;
  }
  if (detail && typeof detail === 'object') {
    const obj = detail as { msg?: unknown; message?: unknown };
    if (typeof obj.msg === 'string') return describeIssue(obj as ValidationIssue);
    if (typeof obj.message === 'string') return obj.message;
  }
  return fallback;
}

/** An Error for a failed response: the readable message, plus the HTTP status and the raw `detail` body. */
export interface ApiResponseError extends Error {
  status: number;
  detail?: unknown;
}

/** Builds the Error thrown for a failed response, with a readable message (and `status` / `detail` attached). */
export async function errorFromResponse(res: Response): Promise<ApiResponseError> {
  const fallback = `API Error: ${res.status} ${res.statusText}`.trim();
  let error: ApiResponseError;
  try {
    const body = await res.json();
    error = new Error(formatApiErrorDetail(body?.detail ?? body?.message, fallback)) as ApiResponseError;
    error.detail = body?.detail;
  } catch {
    error = new Error(fallback) as ApiResponseError;
  }
  error.status = res.status;
  return error;
}

export function isApiResponseError(error: unknown): error is ApiResponseError {
  return error instanceof Error && typeof (error as Partial<ApiResponseError>).status === 'number';
}
