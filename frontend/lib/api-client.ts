import type { AxiosInstance, AxiosResponse } from 'axios';
import axios from 'axios';
import type { Endpoint } from './types';

type ApiClientOptions = {
  headers?: Record<string, string>;
  withCredentials?: boolean;
};

class ApiResponse<T> {
  constructor(
    public data: T,
    public status: number,
    public statusText: string,
  ) {}
  static fromAxios<T>(res: AxiosResponse<T>): ApiResponse<T> {
    return new ApiResponse<T>(res.data, res.status, res.statusText);
  }
}

/**
 * Resolve the API base URL.
 *
 * By default the browser calls the same-origin BFF proxy at `/api`, which
 * forwards requests to the backend and injects the API key server-side
 * (see `app/api/[...path]/route.ts`). The key is never exposed to the client.
 *
 * `NEXT_PUBLIC_API_BASE_URL` is an escape hatch to bypass the proxy and call
 * a backend origin directly — only useful when the backend is public and
 * unauthenticated. Leave it unset for normal deployments.
 */
function getApiBaseURL(): string {
  const explicitBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (explicitBaseUrl) {
    return explicitBaseUrl.replace(/\/+$/, '');
  }
  return '/api';
}

export class ApiClient {
  private axiosInstance: AxiosInstance;

  constructor(baseURL: string, options: ApiClientOptions = {}) {
    this.axiosInstance = axios.create({
      baseURL,
      headers: options.headers,
      withCredentials: options.withCredentials ?? false,
    });
  }

  async get<T, E extends string>(
    endpoint: Endpoint<E>,
    params?: URLSearchParams,
  ) {
    let url = endpoint as string;
    if (params) {
      url += `?${params.toString()}`;
    }
    return ApiResponse.fromAxios(await this.axiosInstance.get<T>(url));
  }

  async post<T, E extends string, Body = unknown>(
    endpoint: Endpoint<E>,
    body?: Body,
  ) {
    return ApiResponse.fromAxios(
      await this.axiosInstance.post<T>(endpoint, body),
    );
  }

  async patch<T, E extends string, Body = unknown>(
    endpoint: Endpoint<E>,
    body?: Body,
  ) {
    return ApiResponse.fromAxios(
      await this.axiosInstance.patch<T>(endpoint, body),
    );
  }

  async delete<T, E extends string>(endpoint: Endpoint<E>) {
    return ApiResponse.fromAxios(await this.axiosInstance.delete<T>(endpoint));
  }
}

const API_BASE_URL = getApiBaseURL();

export const apiClient = new ApiClient(API_BASE_URL);
