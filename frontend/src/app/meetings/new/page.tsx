"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getAccessToken } from "@/lib/auth";
import { UploadDropzone } from "@/components/UploadDropzone";

export default function NewMeetingPage() {
  const router = useRouter();

  useEffect(() => {
    let isMounted = true;
    getAccessToken().then((token) => {
      if (isMounted && !token) {
        router.push("/login");
      }
    });
    return () => {
      isMounted = false;
    };
  }, [router]);

  return (
    <div className="max-w-4xl mx-auto py-8 px-4 sm:px-6 lg:px-8">
      <div className="mb-8">
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">
          Upload New Meeting
        </h1>
        <p className="text-sm text-slate-500 mt-1">
          Upload an audio or video recording to trigger automatic transcription, diarization, and structured AI intelligence.
        </p>
      </div>

      <UploadDropzone />
    </div>
  );
}
