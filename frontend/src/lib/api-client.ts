import { errorFromResponse } from './api-errors';

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

// Helper to convert snake_case to camelCase
function toCamelCase(str: string): string {
  return str.replace(/_([a-z])/g, (g) => g[1].toUpperCase());
}

// Helper to convert camelCase to snake_case
function toSnakeCase(str: string): string {
  return str.replace(/[A-Z]/g, letter => `_${letter.toLowerCase()}`);
}

// Helper to recursively convert object keys from snake_case to camelCase
function convertKeysToCamelCase(obj: any): any {
  if (Array.isArray(obj)) {
    return obj.map(v => convertKeysToCamelCase(v));
  } else if (obj !== null && obj.constructor === Object) {
    return Object.keys(obj).reduce(
      (result, key) => {
        result[toCamelCase(key)] = convertKeysToCamelCase(obj[key]);
        return result;
      },
      {} as any
    );
  }
  return obj;
}

// Helper to recursively convert object keys from camelCase to snake_case
function convertKeysToSnakeCase(obj: any): any {
  if (Array.isArray(obj)) {
    return obj.map(v => convertKeysToSnakeCase(v));
  } else if (obj !== null && obj.constructor === Object) {
    return Object.keys(obj).reduce(
      (result, key) => {
        result[toSnakeCase(key)] = convertKeysToSnakeCase(obj[key]);
        return result;
      },
      {} as any
    );
  }
  return obj;
}

const getAuthHeaders = (): Record<string, string> => {
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('access_token');
    if (token) {
      return { Authorization: `Bearer ${token}` };
    }
  }
  return {};
};

export const apiClient = {
  get: async (endpoint: string) => {
    const res = await fetch(`${API_URL}${endpoint}`, {
      headers: { ...getAuthHeaders() }
    });
    if (!res.ok) {
      throw await errorFromResponse(res);
    }
    const data = await res.json();
    return convertKeysToCamelCase(data);
  },
  
  post: async (endpoint: string, body: any, isFormUrlEncoded = false) => {
    const headers: any = {
      ...getAuthHeaders(),
    };
    
    let reqBody = body;
    if (!isFormUrlEncoded) {
      headers['Content-Type'] = 'application/json';
      reqBody = JSON.stringify(convertKeysToSnakeCase(body));
    }
    
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: 'POST',
      headers,
      body: reqBody,
    });
    if (!res.ok) {
      throw await errorFromResponse(res);
    }
    const data = await res.json();
    return convertKeysToCamelCase(data);
  },

  patch: async (endpoint: string, body: any) => {
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(convertKeysToSnakeCase(body)),
    });
    if (!res.ok) {
      throw await errorFromResponse(res);
    }
    const data = await res.json();
    return convertKeysToCamelCase(data);
  },

  put: async (endpoint: string, body: any) => {
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(convertKeysToSnakeCase(body)),
    });
    if (!res.ok) {
      throw await errorFromResponse(res);
    }
    const data = await res.json();
    return convertKeysToCamelCase(data);
  },

  delete: async (endpoint: string) => {
    const res = await fetch(`${API_URL}${endpoint}`, {
      method: 'DELETE',
      headers: { ...getAuthHeaders() }
    });
    if (!res.ok) {
      throw await errorFromResponse(res);
    }
    return true;
  }
};
