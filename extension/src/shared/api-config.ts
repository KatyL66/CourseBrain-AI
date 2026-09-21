const rawBase = import.meta.env.VITE_API_BASE?.replace(/\/$/, "") || "http://localhost:8001";

export const API_BASE = rawBase;
export const API_KEY = import.meta.env.VITE_API_KEY || "";

export function isLocalApi(base: string = API_BASE): boolean {
  try {
    const host = new URL(base).hostname;
    return host === "localhost" || host === "127.0.0.1";
  } catch {
    return true;
  }
}
