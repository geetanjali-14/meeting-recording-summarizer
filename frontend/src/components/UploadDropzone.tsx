"use client";

import { ChangeEvent, DragEvent, FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";

const MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024; // 500 MB
const ALLOWED_MIME_TYPES = [
  "audio/wav",
  "audio/x-wav",
  "audio/mpeg",
  "audio/mp3",
  "audio/mp4",
  "audio/m4a",
  "audio/x-m4a",
  "audio/webm",
  "video/mp4",
  "video/webm",
  "video/quicktime",
];

export function UploadDropzone() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [meetingDate, setMeetingDate] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [statusText, setStatusText] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);

  const router = useRouter();

  const validateFile = (selectedFile: File): string | null => {
    if (selectedFile.size > MAX_FILE_SIZE_BYTES) {
      return `File size (${(selectedFile.size / (1024 * 1024)).toFixed(
        1
      )} MB) exceeds the 500 MB limit.`;
    }
    const type = selectedFile.type.toLowerCase();
    const name = selectedFile.name.toLowerCase();
    const isAllowedExt = [".wav", ".mp3", ".m4a", ".mp4", ".webm", ".mov"].some(
      (ext) => name.endsWith(ext)
    );
    if (!type && !isAllowedExt) {
      return "Unsupported file type. Please upload a standard audio or video file.";
    }
    if (type && !ALLOWED_MIME_TYPES.includes(type) && !isAllowedExt) {
      return `Unsupported MIME type: ${type}. Please upload MP4, MP3, WAV, M4A, or WebM.`;
    }
    return null;
  };

  const handleFileSelection = (selectedFile: File) => {
    const error = validateFile(selectedFile);
    if (error) {
      setErrorMessage(error);
      setFile(null);
      return;
    }
    setErrorMessage(null);
    setFile(selectedFile);
    if (!title) {
      const cleanName = selectedFile.name.replace(/\.[^/.]+$/, "").replace(/[-_]/g, " ");
      setTitle(cleanName.charAt(0).toUpperCase() + cleanName.slice(1));
    }
  };

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleDrop = (e: DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelection(e.dataTransfer.files[0]);
    }
  };

  const handleFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelection(e.target.files[0]);
    }
  };

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (!file) {
      setErrorMessage("Please select a recording file to upload.");
      return;
    }
    if (!title.trim()) {
      setErrorMessage("Please enter a meeting title.");
      return;
    }

    try {
      setUploading(true);
      setErrorMessage(null);
      setStatusText("1. Initiating upload and requesting pre-signed URL...");

      // Step 1: Initiate meeting & request pre-signed upload URL
      const createRes = await api.createMeeting({
        title: title.trim(),
        description: description.trim() || undefined,
        meeting_date: meetingDate,
        filename: file.name,
        content_type: file.type || "application/octet-stream",
        file_size_bytes: file.size,
      });

      const { meeting_id, upload_url, upload_token } = createRes.data;

      // Step 2: Upload directly to Cloudflare R2 via XMLHttpRequest with progress
      setStatusText("2. Uploading media directly to private storage...");
      await api.uploadFileToStorage(upload_url, file, (percent) => {
        setProgress(percent);
      });

      // Step 3: Confirm upload completion with backend
      setStatusText("3. Confirming upload and queueing ingestion pipeline...");
      await api.confirmUpload(meeting_id, upload_token);

      setStatusText("Complete! Redirecting to meeting processing view...");
      router.push(`/meetings/${meeting_id}`);
    } catch (err) {
      setUploading(false);
      setProgress(0);
      setStatusText("");
      if (err instanceof ApiError) {
        setErrorMessage(`Upload error (${err.code}): ${err.message}`);
      } else if (err instanceof Error) {
        setErrorMessage(err.message);
      } else {
        setErrorMessage("An unknown error occurred during upload.");
      }
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6">
      {errorMessage && (
        <div className="p-4 bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg">
          {errorMessage}
        </div>
      )}

      {/* File Dropzone */}
      <div>
        <label className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-2">
          Meeting Recording (Audio / Video up to 500 MB)
        </label>
        <div
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors ${
            isDragging
              ? "border-indigo-500 bg-indigo-50/50"
              : file
              ? "border-emerald-400 bg-emerald-50/30"
              : "border-slate-300 hover:border-slate-400 bg-slate-50/50"
          }`}
          onClick={() => document.getElementById("file-input")?.click()}
        >
          <input
            id="file-input"
            type="file"
            className="hidden"
            accept="audio/*,video/*,.mp4,.mp3,.wav,.m4a,.webm,.mov"
            onChange={handleFileInputChange}
            disabled={uploading}
          />
          {file ? (
            <div className="space-y-1">
              <span className="text-2xl">🎵</span>
              <p className="text-sm font-semibold text-slate-800">{file.name}</p>
              <p className="text-xs text-slate-500">
                {(file.size / (1024 * 1024)).toFixed(2)} MB • Click or drag to replace
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              <span className="text-3xl text-slate-400">🎙️</span>
              <p className="text-sm font-medium text-slate-700">
                Click to browse or drag and drop your recording here
              </p>
              <p className="text-xs text-slate-500">
                Supports WAV, MP3, MP4, M4A, WebM (up to 500 MB)
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Meeting Details */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div>
          <label
            htmlFor="title"
            className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1"
          >
            Meeting Title *
          </label>
          <input
            id="title"
            type="text"
            required
            disabled={uploading}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g. Q4 Sprint Planning"
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <div>
          <label
            htmlFor="meetingDate"
            className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1"
          >
            Meeting Date *
          </label>
          <input
            id="meetingDate"
            type="date"
            required
            disabled={uploading}
            value={meetingDate}
            onChange={(e) => setMeetingDate(e.target.value)}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>
      </div>

      <div>
        <label
          htmlFor="description"
          className="block text-xs font-semibold uppercase tracking-wider text-slate-700 mb-1"
        >
          Description (Optional)
        </label>
        <textarea
          id="description"
          rows={2}
          disabled={uploading}
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Brief discussion topics or context..."
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-900 focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
        />
      </div>

      {/* Upload Progress Bar */}
      {uploading && (
        <div className="space-y-2 bg-slate-50 p-4 border border-slate-200 rounded-lg">
          <div className="flex justify-between text-xs font-medium text-slate-700">
            <span>{statusText}</span>
            <span>{progress}%</span>
          </div>
          <div className="w-full bg-slate-200 rounded-full h-2 overflow-hidden">
            <div
              className="bg-indigo-600 h-2 transition-all duration-200 rounded-full"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      <button
        type="submit"
        disabled={uploading || !file}
        className={`w-full py-2.5 px-4 rounded-md font-semibold text-sm text-white shadow-sm transition-colors ${
          uploading || !file
            ? "bg-slate-400 cursor-not-allowed"
            : "bg-indigo-600 hover:bg-indigo-700"
        }`}
      >
        {uploading ? "Uploading & Processing..." : "Start Processing Meeting"}
      </button>
    </form>
  );
}

