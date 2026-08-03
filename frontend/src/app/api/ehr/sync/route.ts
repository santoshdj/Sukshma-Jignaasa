import { NextRequest, NextResponse } from "next/server";

export const maxDuration = 60; // Allow up to 60 seconds for this endpoint

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const backendUrl = process.env.BACKEND_URL || "http://localhost:8000";

    const response = await fetch(`${backendUrl}/ehr/sync`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(50000), // 50 second timeout
    });

    const data = await response.json();

    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }

    return NextResponse.json(data);
  } catch (error: unknown) {
    console.error("EHR sync proxy error:", error);
    
    if (error instanceof Error && error.name === "TimeoutError") {
      return NextResponse.json(
        { detail: "Backend sync operation timed out. Please try again." },
        { status: 504 }
      );
    }

    return NextResponse.json(
      { detail: "Failed to connect to backend service" },
      { status: 502 }
    );
  }
}
