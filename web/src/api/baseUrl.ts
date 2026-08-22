declare global {
  interface Window {
    baseUrl?: string;
  }
}

export const baseUrl = `${window.location.protocol}//${window.location.host}${window.baseUrl || "/"}`;

/**
 * Return the absolute URL of the login page, including Frigate's optional
 * base path. Hard-coding /login breaks installations mounted below /.
 */
export function getLoginUrl(): string {
  return new URL("login", baseUrl).toString();
}
