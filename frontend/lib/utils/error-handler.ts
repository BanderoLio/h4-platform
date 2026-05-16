import type { AxiosError } from 'axios';

type ApiErrorResponse = {
  error?: string;
  detail?: string | Record<string, unknown> | unknown[];
  message?: string;
  status_code?: number;
};

function getErrorKeyFromStatus(status: number): string {
  switch (status) {
    case 400:
      return 'ValidationError';
    case 401:
      return 'NotAuthenticated';
    case 403:
      return 'PermissionDenied';
    case 404:
      return 'NotFound';
    case 429:
      return 'RateLimitExceeded';
    case 500:
    case 502:
    case 503:
      return 'InternalServerError';
    default:
      return 'UnexpectedError';
  }
}

export function getErrorKey(error: unknown): string {
  if (error instanceof Error) {
    const axiosError = error as AxiosError<ApiErrorResponse>;

    if (
      axiosError.code === 'ECONNABORTED' ||
      axiosError.code === 'ERR_NETWORK' ||
      !axiosError.response
    ) {
      return 'NetworkError';
    }

    if (axiosError.response?.data) {
      const data = axiosError.response.data;
      const status = axiosError.response.status;

      if (typeof data === 'string') {
        return data;
      }

      if (data.error && typeof data.error === 'string') {
        const errorName = data.error;

        return errorName;
      }

      const statusErrorKey = getErrorKeyFromStatus(status);

      return statusErrorKey;
    }

    if (axiosError.response?.status) {
      return getErrorKeyFromStatus(axiosError.response.status);
    }

    return error.message || 'UnexpectedError';
  }

  return 'UnexpectedError';
}

export function getErrorMessage(error: unknown): string {
  const errorKey = getErrorKey(error);

  if (
    errorKey.includes(' ') ||
    errorKey.includes('.') ||
    !/^[A-Z][a-zA-Z]*$/.test(errorKey)
  ) {
    return errorKey;
  }

  return errorKey;
}

export function getTranslatedErrorMessage(
  error: unknown,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
): string {
  const errorKey = getErrorKey(error);

  if (
    errorKey.includes(' ') ||
    errorKey.includes('.') ||
    !/^[A-Z][a-zA-Z]*$/.test(errorKey)
  ) {
    return errorKey;
  }
  try {
    const translated = t(errorKey);

    return translated;
  } catch {
    return t('Errors.default');
  }
}
