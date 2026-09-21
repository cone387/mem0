import { NextResponse } from "next/server";
import { getServerApiUrl } from "@/lib/server-api-url";

export const GET = async () => {
  // Probe the API behind us instead of reporting ok unconditionally:
  // a green healthcheck on a dead backend once hid a multi-day outage.
  try {
    const res = await fetch(`${getServerApiUrl()}/health`, {
      signal: AbortSignal.timeout(3000),
      cache: "no-store",
    });
    if (!res.ok) {
      return NextResponse.json({ status: "unhealthy", api_status: res.status }, { status: 503 });
    }
    return NextResponse.json({ status: "ok" });
  } catch {
    return NextResponse.json({ status: "unhealthy" }, { status: 503 });
  }
};
