/**
 * User API client for Clerk authentication integration.
 */

export interface UserProfile {
  patient_id: string;
  clerk_user_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
}

/**
 * Get current user profile from backend.
 * This maps the Clerk user ID to the internal patient_id.
 *
 * @param clerkToken - Clerk session token from useAuth()
 * @returns User profile with patient_id
 */
export async function getCurrentUser(clerkToken: string): Promise<UserProfile> {
  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || "http://localhost:8000";
  const response = await fetch(`${backendUrl}/users/me`, {
    method: "GET",
    headers: {
      "Authorization": `Bearer ${clerkToken}`,
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(`Failed to get user profile: ${response.status} ${errorText}`);
  }

  return response.json();
}
