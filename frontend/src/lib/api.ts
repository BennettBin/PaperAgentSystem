export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, init);
  } catch (error) {
    throw new Error(
      error instanceof Error && error.message
        ? `无法连接后端 API：${error.message}`
        : "无法连接后端 API",
    );
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.error?.message ?? `请求失败（${response.status}）`);
  }
  return response.json() as Promise<T>;
}

export interface ConversationSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at?: string;
  message_count: number;
}

export interface PaperFile {
  id: string;
  name: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
  parse_status: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  created_at: string;
  metadata?: Record<string, unknown>;
}

export interface EvidenceCitation {
  id: string;
  file_id: string;
  page: number;
  section: string[];
  quote: string;
  bbox: number[];
}

export interface VisualArtifactReference {
  id: string;
  kind: "figure" | "table" | "algorithm";
  label: string;
  caption: string;
  file_id: string;
  page: number;
  section: string[];
  bbox: number[];
  image_url: string;
}

export interface TokenCount {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

export interface ConversationTokenUsage {
  small: TokenCount;
  large: TokenCount;
  total: TokenCount;
}

export interface ConversationDetail extends ConversationSummary {
  messages: ChatMessage[];
  files: PaperFile[];
}

export interface TaskProgressEvent {
  event_id: string;
  task_id: string;
  sequence: number;
  type: string;
  title: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface TaskMonitorSnapshot {
  task_id: string;
  status: string;
  events: TaskProgressEvent[];
  log_path: string;
}

export interface ParseSection {
  id: string;
  section_id: string;
  number?: string | null;
  title: string;
  level: number;
  parent_section_id?: string | null;
  section_path: string[];
  ordinal: number;
  page_start: number;
  page_end: number;
}

export interface ParseChunk {
  chunk_id: string;
  file_id: string;
  section_id?: string | null;
  section_title?: string | null;
  section_path: string[];
  page_start: number;
  page_end: number;
  chunk_index: number;
  chunk_index_in_section: number;
  text: string;
}

export interface ParseResult {
  file: PaperFile;
  parsed_document: Record<string, unknown> | null;
  sections: ParseSection[];
  chunks: ParseChunk[];
}

export interface RetrievalDebugHit {
  chunk_id: string;
  file_id: string;
  section_title?: string | null;
  section_path: string[];
  page_start: number;
  page_end: number;
  score: number;
  retriever: string;
  chunk_index: number;
  chunk_index_in_section: number;
  text: string;
}

export interface RetrievalPreview {
  conversation_id: string;
  question: string;
  file_ids: string[];
  parsed_section_hint?: string | null;
  exact_match_hits: RetrievalDebugHit[];
  section_hits: RetrievalDebugHit[];
  vector_hits: RetrievalDebugHit[];
  bm25_hits: RetrievalDebugHit[];
  merged_hits: RetrievalDebugHit[];
  reranked_hits: RetrievalDebugHit[];
  final_context_sent_to_llm: RetrievalDebugHit[];
}

export type ModelRole = "small" | "large";
export type ModelStage = "base" | "sft" | "rl";

export interface RuntimeModel {
  model_id: string;
  display_name: string;
  serving_model: string;
  role: ModelRole;
  stage: ModelStage;
  version: string;
  installed: boolean;
  callable: boolean;
  size_bytes?: number;
  parameter_size?: string | null;
}

export interface ModelSettings {
  ollama_available: boolean;
  selected: Record<ModelRole, RuntimeModel>;
  models: RuntimeModel[];
}

export interface ModelCheck extends Omit<RuntimeModel, "installed"> {
  available: boolean;
  requires_download: boolean;
}

export const paperApi = {
  async conversations(query = "") {
    return request<{ items: ConversationSummary[] }>(
      `/conversations${query ? `?q=${encodeURIComponent(query)}` : ""}`,
    );
  },
  async createConversation() {
    return request<ConversationSummary>("/conversations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "新对话" }),
    });
  },
  async conversation(id: string) {
    return request<ConversationDetail>(`/conversations/${id}`);
  },
  async deleteConversation(id: string) {
    return request<{
      deleted: boolean;
      conversation_id: string;
      deleted_file_count: number;
    }>(`/conversations/${id}`, { method: "DELETE" });
  },
  async conversationUsage(id: string) {
    return request<ConversationTokenUsage>(`/conversations/${id}/usage`);
  },
  async files() {
    return request<{ items: PaperFile[] }>("/files");
  },
  async upload(conversationId: string, file: File) {
    const body = new FormData();
    body.append("file", file);
    return request<PaperFile & { task_id: string }>(
      `/conversations/${conversationId}/files`,
      { method: "POST", body },
    );
  },
  async send(conversationId: string, content: string, fileIds: string[]) {
    return request<{ task_id: string; status: string }>(
      `/conversations/${conversationId}/messages`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content, file_ids: fileIds }),
      },
    );
  },
  async task(taskId: string) {
    return request<{
      task_id: string;
      status: string;
      result?: unknown;
      error?: string | null;
    }>(`/product-tasks/${taskId}`);
  },
  async taskMonitor(taskId: string) {
    return request<TaskMonitorSnapshot>(
      `/product-tasks/${encodeURIComponent(taskId)}/monitor`,
    );
  },
  subscribeTaskEvents(
    taskId: string,
    onEvent: (event: TaskProgressEvent) => void,
    onError?: () => void,
  ) {
    const source = new EventSource(
      `${API_BASE}/tasks/${encodeURIComponent(taskId)}/events`,
    );
    const eventTypes = [
      "task_started",
      "runtime_routed",
      "model_selected",
      "skill_selected",
      "runtime_fallback",
      "plan_created",
      "step_started",
      "step_completed",
      "tool_started",
      "tool_completed",
      "subagent_started",
      "subagent_completed",
      "multi_agent_started",
      "multi_agent_completed",
      "multi_agent_degraded",
      "multi_agent_failed",
      "multi_agent_revision_started",
      "multi_agent_revision_completed",
      "multi_agent_idempotency_replayed",
      "coordinator_agent_started",
      "coordinator_agent_completed",
      "coordinator_agent_failed",
      "paper_reader_agent_started",
      "paper_reader_agent_completed",
      "paper_reader_agent_failed",
      "evidence_agent_started",
      "evidence_agent_completed",
      "evidence_agent_failed",
      "critic_agent_started",
      "critic_agent_completed",
      "critic_agent_failed",
      "writer_agent_started",
      "writer_agent_completed",
      "writer_agent_failed",
      "verifier_agent_started",
      "verifier_agent_completed",
      "verifier_agent_passed",
      "verifier_agent_failed",
      "verification_completed",
      "verification_failed",
      "task_completed",
      "task_failed",
      "task_cancelled",
    ];
    const receive = (message: MessageEvent<string>) => {
      try {
        onEvent(JSON.parse(message.data) as TaskProgressEvent);
      } catch {
        // Invalid progress payloads are ignored; task polling remains authoritative.
      }
    };
    eventTypes.forEach((type) => source.addEventListener(type, receive as EventListener));
    source.onerror = () => onError?.();
    return () => source.close();
  },
  async debugParse(fileId: string) {
    return request<ParseResult>(`/debug/files/${fileId}/parse`);
  },
  async debugRetrieval(body: {
    conversation_id: string;
    question: string;
    file_ids: string[];
  }) {
    return request<RetrievalPreview>("/debug/retrieval/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  },
  async modelSettings() {
    return request<ModelSettings>("/model-settings");
  },
  async selectModel(role: ModelRole, modelId: string) {
    return request<ModelSettings>("/model-settings/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, model_id: modelId }),
    });
  },
  async checkModel(role: ModelRole, modelName: string) {
    return request<ModelCheck>("/model-settings/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, model_name: modelName }),
    });
  },
  async downloadModel(role: ModelRole, modelName: string) {
    return request<ModelSettings>("/model-settings/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role, model_name: modelName }),
    });
  },
};
