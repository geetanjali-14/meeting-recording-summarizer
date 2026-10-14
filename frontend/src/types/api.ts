export interface MetaEnvelope {
  request_id: string;
  timestamp: string;
  page?: number;
  per_page?: number;
  total_count?: number;
  has_next_page?: boolean;
}

export interface SuccessEnvelope<T> {
  data: T;
  meta: MetaEnvelope;
}

export interface ErrorDetail {
  code: string;
  message: string;
  details?: unknown;
}

export interface ErrorEnvelope {
  error: ErrorDetail;
  meta: MetaEnvelope;
}

export interface MeetingListItem {
  meeting_id: string;
  title: string;
  meeting_date: string;
  status: "ACTIVE" | "ARCHIVED" | "DELETED";
  created_at: string;
}

export interface MeetingRecordingDetail {
  recording_id: string;
  filename: string;
  content_type: string;
  file_size_bytes: number;
  status: "PENDING" | "UPLOADED" | "PROCESSING" | "PROCESSED" | "FAILED";
}

export interface MeetingJobDetail {
  job_id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
  attempt: number;
}

export interface MeetingDetail {
  meeting_id: string;
  title: string;
  description: string | null;
  meeting_date: string;
  status: "ACTIVE" | "ARCHIVED" | "DELETED";
  created_at: string;
  recording: MeetingRecordingDetail | null;
  job: MeetingJobDetail | null;
}

export interface MeetingCreateResponseData {
  meeting_id: string;
  recording_id: string;
  status: string;
  upload_url: string;
  upload_token: string;
  expires_in_seconds: number;
}

export interface ConfirmUploadResponseData {
  meeting_id: string;
  job_id: string;
  status: string;
  job_status: string;
}

export type JobStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type JobStage =
  | "CREATED"
  | "VALIDATING"
  | "EXTRACTING_AUDIO"
  | "TRANSCRIBING"
  | "DIARIZING"
  | "ANALYZING"
  | "VERIFYING"
  | "SAVING"
  | "COMPLETED"
  | "FAILED";

export interface JobStatusResponse {
  meeting_id: string;
  job_id: string;
  celery_task_id: string | null;
  status: JobStatus;
  stage: JobStage;
  attempt: number;
  error_code: string | null;
  error_message: string | null;
}

export interface TranscriptSegment {
  segment_id: string;
  sequence_index: number;
  start_time: number;
  end_time: number;
  speaker_label: string | null;
  speaker: string | null;
  text: string;
}

export interface TranscriptResponse {
  transcript_id: string;
  language: string | null;
  total_duration_seconds: number | null;
  segment_count: number;
  segments: TranscriptSegment[];
}

export interface TopicItem {
  topic_id: string;
  sequence_index: number;
  title: string;
  summary: string | null;
  start_time: number | null;
  end_time: number | null;
}

export interface DecisionItem {
  decision_id: string;
  sequence_index: number;
  decision_text: string;
  confidence: "EXPLICIT" | "INFERRED";
  start_time: number | null;
  end_time: number | null;
  evidence_segment_ids: string[];
}

export interface ActionItem {
  action_item_id: string;
  sequence_index: number;
  action_text: string;
  owner: string | null;
  due_date: string | null;
  start_time: number | null;
  end_time: number | null;
  evidence_segment_ids: string[];
}

export interface RiskItem {
  risk_id: string;
  sequence_index: number;
  risk_text: string;
  start_time: number | null;
  end_time: number | null;
  evidence_segment_ids: string[];
}

export interface OpenQuestionItem {
  question_id: string;
  sequence_index: number;
  question_text: string;
  start_time: number | null;
  end_time: number | null;
  evidence_segment_ids: string[];
}

export interface MeetingAnalysisData {
  analysis_id: string;
  title: string | null;
  executive_summary: string | null;
  model: string;
  estimated_cost_usd: number | null;
  topics: TopicItem[];
  decisions: DecisionItem[];
  action_items: ActionItem[];
  risks: RiskItem[];
  open_questions: OpenQuestionItem[];
}

export interface ChatCitation {
  segment_id: string;
  start_time: number;
  end_time: number;
  speaker: string | null;
  text_snippet: string | null;
}

export interface ChatMessageItem {
  message_id: string;
  session_id: string;
  meeting_id: string;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  content: string;
  citations: ChatCitation[];
  created_at: string;
}

export interface ChatResponseData {
  session_id: string;
  message: ChatMessageItem;
}

export interface ExportResponseData {
  meeting_id: string;
  format: "markdown" | "json";
  filename: string;
  content_type: string;
  content: string;
  metadata: Record<string, unknown>;
}

