const API_BASE = process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000";

export async function apiGet(path: string) {
  const apiKey = localStorage.getItem("tenant_api_key") || "";
  const res = await fetch(`${API_BASE}${path}`, {
    headers: {
      "X-API-Key": apiKey,
    },
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(`GET ${path} failed`);
  }

  return res.json();
}