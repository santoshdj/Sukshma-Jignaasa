"use client";

import { useUser, UserButton, useAuth } from "@clerk/nextjs";
import { useEffect, useState } from "react";
import { EHRConnectionStatus } from "@/components/EHRConnectionStatus";
import { getCurrentUser, type UserProfile } from "@/lib/userApi";

export default function HomePage() {
  const { user, isLoaded } = useUser();
  const { getToken } = useAuth();
  const [userProfile, setUserProfile] = useState<UserProfile | null>(null);
  const [loadingProfile, setLoadingProfile] = useState(true);

  // Fetch user profile from backend to get patient_id
  useEffect(() => {
    async function fetchUserProfile() {
      if (!user) return;

      try {
        const token = await getToken();
        if (!token) {
          console.error("No Clerk token available");
          setLoadingProfile(false);
          return;
        }

        const profile = await getCurrentUser(token);
        setUserProfile(profile);
      } catch (error) {
        console.error("Failed to fetch user profile:", error);
      } finally {
        setLoadingProfile(false);
      }
    }

    if (isLoaded && user) {
      fetchUserProfile();
    } else if (isLoaded) {
      setLoadingProfile(false);
    }
  }, [user, isLoaded, getToken]);

  // Show loading state while Clerk initializes
  if (!isLoaded || loadingProfile) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-slate-500">Loading...</div>
      </div>
    );
  }

  // Use patient_id from backend (fallback to Clerk user ID if not loaded yet)
  const patientId = userProfile?.patient_id || user?.id || "anonymous";

  return (
    <main className="max-w-lg mx-auto px-4 py-12 space-y-6">
      {/* User profile section */}
      <div className="flex justify-end mb-4">
        <div className="flex items-center gap-3">
          <div className="text-right">
            <p className="text-sm font-medium text-slate-700">{user?.firstName || "Patient"}</p>
            <p className="text-xs text-slate-500">{user?.primaryEmailAddress?.emailAddress}</p>
          </div>
          <UserButton 
            afterSignOutUrl="/sign-in"
            appearance={{
              elements: {
                avatarBox: "w-10 h-10",
              },
            }}
          />
        </div>
      </div>

      <div className="text-center pt-4 pb-2">
        <h1 className="text-3xl font-bold text-slate-800 mb-1">सूक्ष्म जिज्ञासा</h1>
        <p className="text-xs font-medium text-slate-400 tracking-widest uppercase mb-3">
          Sukshma Jijñāsā &nbsp;·&nbsp; The Subtle Inquiry
        </p>
        <p className="text-slate-500 text-sm">Your AI companion for rare disease pattern tracking.</p>
      </div>

      {/* EHR connection — triggers redirect to Medblocks OAuth */}
      <EHRConnectionStatus patientId={patientId} />

      {/* Navigation */}
      <div className="flex flex-col gap-3 pt-2">
        <a
          href="/check-in"
          className="block text-center bg-brand-600 hover:bg-brand-700 text-white font-semibold px-6 py-3 rounded-xl transition-colors"
        >
          Log today →
        </a>
        <a
          href="/hypothesis"
          className="block text-center bg-white border border-slate-200 hover:border-brand-400 text-slate-700 font-semibold px-6 py-3 rounded-xl transition-colors"
        >
          View pattern analysis →
        </a>
      </div>
    </main>
  );
}
