import {
  ConfirmUploadResponseData,
  JobStatusResponse,
  MeetingAnalysisData,
  MeetingCreateResponseData,
  MeetingDetail,
  MeetingListItem,
  SuccessEnvelope,
  TranscriptResponse,
} from "@/types/api";
import { getStoredToken } from "./auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export class ApiError extends Error {
  code: string;
  status: number;
  details?: unknown;

  constructor(message: string, code: string, status: number, details?: unknown) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<SuccessEnvelope<T>> {
  const token = getStoredToken();
  const headers = new Headers(options.headers || {});

  if (!headers.has("Content-Type") && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (token && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const url = `${API_BASE_URL}${path}`;
  const response = await fetch(url, {
    ...options,
    headers,
  });

  if (response.status === 204) {
    return {
      data: null as unknown as T,
      meta: { request_id: "", timestamp: new Date().toISOString() },
    };
  }

  const data = await response.json();

  if (!response.ok) {
    const errorDetail = data?.error || {
      code: "UNKNOWN_ERROR",
      message: response.statusText,
    };
    throw new ApiError(
      errorDetail.message || "An unexpected API error occurred",
      errorDetail.code || "API_ERROR",
      response.status,
      errorDetail.details
    );
  }

  return data as SuccessEnvelope<T>;
}

export const api = {
  // Meetings
  async listMeetings(page = 1, perPage = 20): Promise<SuccessEnvelope<MeetingListItem[]>> {
    return request<MeetingListItem[]>(`/api/v1/meetings?page=${page}&per_page=${perPage}`);
  },

  async getMeeting(meetingId: string): Promise<SuccessEnvelope<MeetingDetail>> {
    return request<MeetingDetail>(`/api/v1/meetings/${meetingId}`);
  },

  async createMeeting(payload: {
    title: string;
    description?: string;
    meeting_date: string;
    filename: string;
    content_type: string;
    file_size_bytes: number;
  }): Promise<SuccessEnvelope<MeetingCreateResponseData>> {
    return request<MeetingCreateResponseData>("/api/v1/meetings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  async confirmUpload(
    meetingId: string,
    recordingId: string,
    uploadToken: string
  ): Promise<SuccessEnvelope<ConfirmUploadResponseData>> {
    return request<ConfirmUploadResponseData>(
      `/api/v1/meetings/${meetingId}/confirm-upload`,
      {
        method: "POST",
        body: JSON.stringify({
          recording_id: recordingId,
          upload_token: uploadToken,
        }),
      }
    );
  },

  async deleteMeeting(meetingId: string): Promise<void> {
    await request<void>(`/api/v1/meetings/${meetingId}`, {
      method: "DELETE",
    });
  },

  // Status & Transcript
  async getStatus(meetingId: string): Promise<SuccessEnvelope<JobStatusResponse>> {
    return request<JobStatusResponse>(`/api/v1/meetings/${meetingId}/status`);
  },

  async getTranscript(meetingId: string): Promise<SuccessEnvelope<TranscriptResponse>> {
    return request<TranscriptResponse>(`/api/v1/meetings/${meetingId}/transcript`);
  },

  // Intelligence Analysis
  async getAnalysis(meetingId: string): Promise<SuccessEnvelope<MeetingAnalysisData>> {
    return request<MeetingAnalysisData>(`/api/v1/meetings/${meetingId}/analysis`);
  },

  // Conversational Q&A
  async sendChatMessage(
    meetingId: string,
    question: string,
    sessionId?: string
  ): Promise<SuccessEnvelope<{ session_id: string; message: import("@/types/api").ChatMessageItem }>> {
    return request<{ session_id: string; message: import("@/types/api").ChatMessageItem }>(
      `/api/v1/meetings/${meetingId}/chat`,
      {
        method: "POST",
        body: JSON.stringify({ question, session_id: sessionId || undefined }),
      }
    );
  },

  async getChatMessages(
    meetingId: string,
    sessionId?: string
  ): Promise<SuccessEnvelope<import("@/types/api").ChatMessageItem[]>> {
    const query = sessionId ? `?session_id=${sessionId}` : "";
    return request<import("@/types/api").ChatMessageItem[]>(
      `/api/v1/meetings/${meetingId}/chat/messages${query}`
    );
  },

  // Direct storage upload with progress
  uploadFileToStorage(
    presignedUrl: string,
    file: File,
    onProgress?: (percent: number) => void
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", presignedUrl, true);
      xhr.setRequestHeader("Content-Type", file.type || "application/octet-stream");

      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable && onProgress) {
          const percent = Math.round((event.loaded / event.total) * 100);
          onProgress(percent);
        }
      };

      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          resolve();
        } else {
          reject(
            new ApiError(
              `Storage direct upload failed with status ${xhr.status}`,
              "STORAGE_UPLOAD_FAILED",
              xhr.status
            )
          );
        }
      };

      xhr.onerror = () => {
        reject(
          new ApiError("Network error occurred during storage upload", "NETWORK_ERROR", 0)
        );
      };

      xhr.send(file);
    });
  },
};

