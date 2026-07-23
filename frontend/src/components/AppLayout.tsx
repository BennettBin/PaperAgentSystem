"use client";

import React from "react";

import {
  ChatMessage,
  ConversationTokenUsage,
  ConversationSummary,
  EvidenceCitation,
  PaperFile,
  ParseResult,
  paperApi,
  RetrievalDebugHit,
  RetrievalPreview,
  TaskProgressEvent,
  VisualArtifactReference,
} from "../lib/api";
import { ConversationList } from "./ConversationList";
import { MessageComposer } from "./MessageComposer";
import { ModelProfileManager } from "./ModelProfileManager";

const Icon = ({ children, size = 20 }: { children: React.ReactNode; size?: number }) => (
  <svg aria-hidden="true" className="icon" height={size} viewBox="0 0 24 24" width={size}>
    {children}
  </svg>
);

export interface AppLayoutProps {}

const emptyUsage: ConversationTokenUsage = {
  small: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  large: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
  total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
};

const progressLabel = (event: TaskProgressEvent) => {
  const labels: Record<string, string> = {
    runtime_routed: "已选择执行路径",
    model_selected: "已选择模型 Profile",
    runtime_fallback: "高级路径未晋级，已回退安全流程",
    plan_created: "已生成执行计划",
    step_started: "正在执行计划步骤",
    step_completed: "计划步骤已完成",
    tool_started: "正在调用工具",
    tool_completed: "工具调用完成",
    subagent_started: "多 Agent 协作已开始",
    subagent_completed: "Agent 子任务已完成",
    verification_completed: "回答核验完成",
    verification_failed: "回答核验失败",
  };
  return event.title || labels[event.type] || "Agent 进度更新";
};

const skillEventDetail = (event: TaskProgressEvent) => {
  if (event.type !== "skill_selected") return "";
  const version = typeof event.data.skill_version === "string" ? event.data.skill_version : "";
  const profile = typeof event.data.model_profile === "string" ? event.data.model_profile : "";
  return [version ? `v${version}` : "", profile ? `Profile: ${profile}` : ""]
    .filter(Boolean)
    .join(" · ");
};

const completedEventTypes = new Set([
  "step_completed",
  "tool_completed",
  "subagent_completed",
  "verification_completed",
  "task_completed",
]);

export const TaskStatusMonitor = ({
  status,
  events,
  logPath,
  onOpen,
}: {
  status: string;
  events: TaskProgressEvent[];
  logPath: string;
  onOpen?: () => void | Promise<void>;
}) => {
  const [open, setOpen] = React.useState(false);
  return (
    <div className="task-monitor-wrap">
      <div className="task-status-row">
        <p className="task-status">{status}</p>
        <button
          type="button"
          className="task-monitor-button"
          aria-expanded={open}
          onClick={() => {
            const next = !open;
            setOpen(next);
            if (next) void onOpen?.();
          }}
        >
          监控
        </button>
      </div>
      {open ? (
        <section
          className="task-monitor-popover"
          role="dialog"
          aria-label="Agent 任务监控"
        >
          <header>
            <div>
              <strong>Agent 工作进展</strong>
              <small>仅展示可公开的执行阶段，不包含模型内部推理。</small>
            </div>
            <button type="button" aria-label="关闭 Agent 任务监控" onClick={() => setOpen(false)}>
              ×
            </button>
          </header>
          {events.length ? (
            <ol className="task-monitor-events">
              {events.map((event, index) => {
                const completed = completedEventTypes.has(event.type);
                const active = index === events.length - 1 && !completed;
                return (
                  <li className={active ? "active" : "completed"} key={event.event_id}>
                    <span aria-hidden="true" />
                    <div>
                      <strong>{event.title}</strong>
                      {skillEventDetail(event) ? <small>{skillEventDetail(event)}</small> : null}
                      <time dateTime={event.created_at}>
                        {new Date(event.created_at).toLocaleTimeString("zh-CN", {
                          hour12: false,
                        })}
                      </time>
                    </div>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="task-monitor-empty">正在等待后台上报第一个执行步骤…</p>
          )}
          <footer>
            <span>详细日志</span>
            <code>{logPath || "日志路径准备中…"}</code>
          </footer>
        </section>
      ) : null}
    </div>
  );
};

export const AssistantMessage = ({ message }: { message: ChatMessage }) => {
  const evidence = Array.isArray(message.metadata?.evidence)
    ? (message.metadata?.evidence as EvidenceCitation[])
    : [];
  const visualArtifacts = Array.isArray(message.metadata?.visual_artifacts)
    ? (message.metadata?.visual_artifacts as VisualArtifactReference[])
    : [];
  const [hoveredReference, setHoveredReference] = React.useState<string | null>(null);
  const [pinnedReference, setPinnedReference] = React.useState<string | null>(null);
  const byId = new Map(evidence.map((item) => [item.id, item]));
  const visualByLabel = new Map(
    visualArtifacts.map((item) => [item.label.toLocaleLowerCase(), item]),
  );
  const visualLabels = [...visualByLabel.keys()].sort(
    (left, right) => right.length - left.length,
  );
  const referencePattern = new RegExp(
    `(\\[E\\d+\\]${
      visualLabels.length
        ? `|${visualLabels.map((label) => label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")}`
        : ""
    })`,
    "gi",
  );
  const referencedVisualIds = new Set<string>();
  const togglePinned = (key: string) => {
    setPinnedReference((current) => (current === key ? null : key));
  };
  const isOpen = (key: string) =>
    hoveredReference === key || pinnedReference === key;

  return (
    <div className="chat-message-assistant">
      <div>
        {message.content.split(referencePattern).map((part, index) => {
          const id = part.match(/^\[(E\d+)\]$/)?.[1];
          const citation = id ? byId.get(id) : undefined;
          if (citation) {
            const key = `citation:${citation.id}`;
            return (
              <span
                className="inline-reference-shell"
                data-testid={`inline-reference-${citation.id}`}
                key={`${part}-${index}`}
                onMouseEnter={() => setHoveredReference(key)}
                onMouseLeave={() => setHoveredReference(null)}
              >
                <button
                  aria-expanded={isOpen(key)}
                  className="inline-citation"
                  onBlur={() => setHoveredReference(null)}
                  onClick={() => togglePinned(key)}
                  onFocus={() => setHoveredReference(key)}
                  type="button"
                >
                  [{id}]
                </button>
                {isOpen(key) ? (
                  <span className="reference-popover citation-popover" role="tooltip">
                    <span>
                      <strong>{citation.id}</strong>
                      <small>第 {citation.page} 页</small>
                    </span>
                    <span>{citation.quote}</span>
                  </span>
                ) : null}
              </span>
            );
          }
          const visual = visualByLabel.get(part.toLocaleLowerCase());
          if (visual) {
            referencedVisualIds.add(visual.id);
            const key = `visual:${visual.id}`;
            return (
              <span
                className="inline-reference-shell"
                data-testid={`inline-reference-${visual.id}`}
                key={`${part}-${index}`}
                onMouseEnter={() => setHoveredReference(key)}
                onMouseLeave={() => setHoveredReference(null)}
              >
                <button
                  aria-expanded={isOpen(key)}
                  className="inline-citation inline-visual-reference"
                  onBlur={() => setHoveredReference(null)}
                  onClick={() => togglePinned(key)}
                  onFocus={() => setHoveredReference(key)}
                  type="button"
                >
                  {visual.label}
                </button>
                {isOpen(key) ? (
                  <span className="reference-popover visual-popover" role="tooltip">
                    <img
                      alt={`${visual.label}，论文第 ${visual.page} 页`}
                      loading="lazy"
                      src={visual.image_url}
                    />
                    <span>
                      <strong>{visual.label}</strong>
                      <small>第 {visual.page} 页</small>
                      {visual.caption ? <span>{visual.caption}</span> : null}
                    </span>
                  </span>
                ) : null}
              </span>
            );
          }
          return <React.Fragment key={`${part}-${index}`}>{part}</React.Fragment>;
        })}
      </div>
      {visualArtifacts.some((artifact) => !referencedVisualIds.has(artifact.id)) ? (
        <div className="visual-reference-list" aria-label="回答引用的论文截图">
          {visualArtifacts
            .filter((artifact) => !referencedVisualIds.has(artifact.id))
            .map((artifact) => {
              const key = `visual:${artifact.id}`;
              return (
                <span
                  className="inline-reference-shell"
                  data-testid={`inline-reference-${artifact.id}`}
                  key={artifact.id}
                  onMouseEnter={() => setHoveredReference(key)}
                  onMouseLeave={() => setHoveredReference(null)}
                >
                  <button
                    aria-expanded={isOpen(key)}
                    className="inline-citation inline-visual-reference"
                    onBlur={() => setHoveredReference(null)}
                    onClick={() => togglePinned(key)}
                    onFocus={() => setHoveredReference(key)}
                    type="button"
                  >
                    {artifact.label}
                  </button>
                  {isOpen(key) ? (
                    <span className="reference-popover visual-popover" role="tooltip">
                      <img
                        alt={`${artifact.label}，论文第 ${artifact.page} 页`}
                        loading="lazy"
                        src={artifact.image_url}
                      />
                      <span>
                        <strong>{artifact.label}</strong>
                        <small>第 {artifact.page} 页</small>
                        {artifact.caption ? <span>{artifact.caption}</span> : null}
                      </span>
                    </span>
                  ) : null}
                </span>
              );
            })}
        </div>
      ) : null}
    </div>
  );
};

const RetrievalStage = ({
  title,
  hits,
  finalIds,
}: {
  title: string;
  hits: RetrievalDebugHit[];
  finalIds: Set<string>;
}) => (
  <section className="diagnostic-stage">
    <h4>{title}</h4>
    {hits.length ? (
      hits.map((hit) => (
        <article
          className={finalIds.has(hit.chunk_id) ? "diagnostic-hit final" : "diagnostic-hit"}
          key={`${title}-${hit.chunk_id}`}
        >
          <header>
            <strong>{hit.section_path.join(" / ") || hit.section_title || "未识别章节"}</strong>
            <span>{hit.retriever} · {hit.score.toFixed(4)} · p{hit.page_start}-{hit.page_end}</span>
          </header>
          <small>{hit.chunk_id} · chunk {hit.chunk_index_in_section}</small>
          <p>{hit.text}</p>
        </article>
      ))
    ) : (
      <p className="diagnostic-empty">无结果</p>
    )}
  </section>
);

export const AppLayout: React.FC<AppLayoutProps> = () => {
  const [conversations, setConversations] = React.useState<ConversationSummary[]>([]);
  const [selectedConversation, setSelectedConversation] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<ChatMessage[]>([]);
  const [files, setFiles] = React.useState<PaperFile[]>([]);
  const [libraryFiles, setLibraryFiles] = React.useState<PaperFile[]>([]);
  const [searchOpen, setSearchOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const [modelSettingsOpen, setModelSettingsOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [status, setStatus] = React.useState("");
  const [activeTaskId, setActiveTaskId] = React.useState<string | null>(null);
  const [taskEvents, setTaskEvents] = React.useState<TaskProgressEvent[]>([]);
  const [taskLogPath, setTaskLogPath] = React.useState("");
  const [error, setError] = React.useState("");
  const [usage, setUsage] = React.useState<ConversationTokenUsage>(emptyUsage);
  const [usageOpen, setUsageOpen] = React.useState(true);
  const [diagnosticOpen, setDiagnosticOpen] = React.useState(false);
  const [parseResult, setParseResult] = React.useState<ParseResult | null>(null);
  const [selectedDebugSection, setSelectedDebugSection] = React.useState<string | null>(null);
  const [retrievalQuestion, setRetrievalQuestion] = React.useState("");
  const [retrievalPreview, setRetrievalPreview] = React.useState<RetrievalPreview | null>(null);
  const [diagnosticLoading, setDiagnosticLoading] = React.useState(false);
  const fileInputRef = React.useRef<HTMLInputElement>(null);
  const mountedRef = React.useRef(true);

  React.useEffect(
    () => () => {
      mountedRef.current = false;
    },
    [],
  );

  const refreshConversations = React.useCallback(async () => {
    try {
      const result = await paperApi.conversations();
      setConversations(result.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载会话失败");
    }
  }, []);

  React.useEffect(() => {
    void refreshConversations();
  }, [refreshConversations]);

  const refreshUsage = React.useCallback(async (conversationId: string) => {
    try {
      setUsage(await paperApi.conversationUsage(conversationId));
    } catch {
      // Token accounting is informational and must not interrupt the conversation.
    }
  }, []);

  React.useEffect(() => {
    if (!selectedConversation) {
      setUsage(emptyUsage);
      return;
    }
    void refreshUsage(selectedConversation);
    const timer = window.setInterval(
      () => void refreshUsage(selectedConversation),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [refreshUsage, selectedConversation]);

  const loadConversation = React.useCallback(async (id: string) => {
    setError("");
    try {
      const detail = await paperApi.conversation(id);
      setSelectedConversation(id);
      setMessages(detail.messages);
      setFiles(detail.files);
      void refreshUsage(id);
      setLibraryOpen(false);
      setModelSettingsOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载会话失败");
    }
  }, [refreshUsage]);

  const deleteConversation = async (id: string, title: string) => {
    const confirmed = window.confirm(
      `彻底删除“${title}”？这会删除该历史会话、聊天记录和关联上传文件，且不可恢复。`,
    );
    if (!confirmed) return;
    setBusy(true);
    setError("");
    try {
      await paperApi.deleteConversation(id);
      setConversations((current) => current.filter((item) => item.id !== id));
      if (selectedConversation === id) {
        setSelectedConversation(null);
        setMessages([]);
        setFiles([]);
        setUsage(emptyUsage);
      }
      await refreshConversations();
      setStatus("历史会话和关联文件已彻底删除");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "删除会话失败");
    } finally {
      setBusy(false);
    }
  };

  const startNewChat = async () => {
    setBusy(true);
    setError("");
    try {
      const conversation = await paperApi.createConversation();
      setConversations((current) => [conversation, ...current]);
      setSelectedConversation(conversation.id);
      setMessages([]);
      setFiles([]);
      setUsage(emptyUsage);
      setSearch("");
      setSearchOpen(false);
      setLibraryOpen(false);
      setModelSettingsOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "创建会话失败");
    } finally {
      setBusy(false);
    }
  };

  const ensureConversation = async () => {
    if (selectedConversation) return selectedConversation;
    const conversation = await paperApi.createConversation();
    setConversations((current) => [conversation, ...current]);
    setSelectedConversation(conversation.id);
    return conversation.id;
  };

  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const selected = event.target.files?.[0];
    event.target.value = "";
    if (!selected) return;
    setBusy(true);
    setError("");
    setStatus(`正在上传 ${selected.name}…`);
    const optimistic: PaperFile = {
      id: `upload-${selected.name}`,
      name: selected.name,
      content_type: selected.type,
      size_bytes: selected.size,
      created_at: new Date().toISOString(),
      parse_status: "uploading",
    };
    setFiles((current) => [...current, optimistic]);
    try {
      const conversationId = await ensureConversation();
      const uploaded = await paperApi.upload(conversationId, selected);
      setFiles((current) => [
        ...current.filter((item) => item.id !== optimistic.id),
        uploaded,
      ]);
      setStatus("文件已上传，后台正在解析和建立索引");
      await refreshConversations();
    } catch (reason) {
      setFiles((current) => current.filter((item) => item.id !== optimistic.id));
      setError(reason instanceof Error ? reason.message : "上传失败");
      setStatus("");
    } finally {
      setBusy(false);
    }
  };

  const waitForTask = async (taskId: string, conversationId: string) => {
    setActiveTaskId(taskId);
    setTaskLogPath(`runtime/logs/agent/${taskId}.jsonl`);
    const recordEvent = (event: TaskProgressEvent) => {
      setTaskEvents((current) => {
        const withoutDuplicate = current.filter(
          (item) => item.event_id !== event.event_id,
        );
        return [...withoutDuplicate, event].sort((left, right) => left.sequence - right.sequence);
      });
      setStatus(progressLabel(event));
    };
    try {
      const snapshot = await paperApi.taskMonitor(taskId);
      if (mountedRef.current) {
        setTaskEvents(Array.isArray(snapshot.events) ? snapshot.events : []);
        setTaskLogPath(snapshot.log_path || `runtime/logs/agent/${taskId}.jsonl`);
      }
    } catch {
      // SSE and task polling remain authoritative if history hydration is unavailable.
    }
    const closeEvents = paperApi.subscribeTaskEvents(
      taskId,
      (event) => {
        if (mountedRef.current) recordEvent(event);
      },
    );
    try {
      for (let attempt = 0; attempt < 180; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1000));
        if (!mountedRef.current) return;
        const task = await paperApi.task(taskId);
        void refreshUsage(conversationId);
        if (task.status === "completed") {
          setStatus("回答已生成");
          await loadConversation(conversationId);
          await refreshConversations();
          return;
        }
        if (task.status === "waiting_user") {
          setStatus("请回答上方的澄清问题，系统将继续原任务");
          await loadConversation(conversationId);
          return;
        }
        if (task.status === "failed" || task.status === "cancelled") {
          throw new Error(task.error ?? `任务${task.status}`);
        }
        if (attempt === 0) {
          setStatus(task.status === "running" ? "正在执行 Agent 任务…" : "任务排队中…");
        }
      }
      throw new Error("任务等待超时");
    } finally {
      closeEvents();
    }
  };

  const refreshActiveTaskMonitor = async () => {
    if (!activeTaskId) return;
    try {
      const snapshot = await paperApi.taskMonitor(activeTaskId);
      if (!mountedRef.current) return;
      setTaskEvents(Array.isArray(snapshot.events) ? snapshot.events : []);
      setTaskLogPath(snapshot.log_path || `runtime/logs/agent/${activeTaskId}.jsonl`);
    } catch {
      // The live SSE stream remains available if a history refresh fails.
    }
  };

  const submit = async (content: string) => {
    setBusy(true);
    setError("");
    const optimistic: ChatMessage = {
      id: `local-${Date.now()}`,
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    try {
      const conversationId = await ensureConversation();
      const task = await paperApi.send(
        conversationId,
        content,
        files.filter((item) => item.parse_status !== "uploading").map((item) => item.id),
      );
      setTaskEvents([]);
      setStatus("任务已提交");
      await waitForTask(task.task_id, conversationId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "任务执行失败");
      setStatus("");
    } finally {
      setBusy(false);
    }
  };

  const openLibrary = async () => {
    setLibraryOpen(true);
    setModelSettingsOpen(false);
    setError("");
    try {
      const result = await paperApi.files();
      setLibraryFiles(result.items);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载文件库失败");
    }
  };

  const openParseDiagnostics = async (file: PaperFile) => {
    setDiagnosticOpen(true);
    setDiagnosticLoading(true);
    setError("");
    try {
      const result = await paperApi.debugParse(file.id);
      setParseResult(result);
      setSelectedDebugSection(result.sections[0]?.section_id ?? null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载解析结果失败");
    } finally {
      setDiagnosticLoading(false);
    }
  };

  const runRetrievalDiagnostics = async () => {
    if (!selectedConversation) {
      setError("请先选择或创建一个会话");
      return;
    }
    if (!retrievalQuestion.trim()) {
      setError("请输入检索诊断问题");
      return;
    }
    setDiagnosticOpen(true);
    setDiagnosticLoading(true);
    setError("");
    try {
      setRetrievalPreview(
        await paperApi.debugRetrieval({
          conversation_id: selectedConversation,
          question: retrievalQuestion,
          file_ids: files
            .filter((item) => item.parse_status !== "uploading")
            .map((item) => item.id),
        }),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "检索诊断失败");
    } finally {
      setDiagnosticLoading(false);
    }
  };

  const visibleConversations = conversations.filter((conversation) =>
    (conversation.title ?? "").toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );

  return (
    <div className={`app-shell${usageOpen ? " usage-open" : ""}`}>
      <aside className="app-sidebar">
        <div className="brand-row">
          <div className="brand-mark">P</div>
          <span>PaperAgent</span>
        </div>

        <nav className="primary-nav" aria-label="主要导航">
          <button className="nav-item nav-item-active" disabled={busy} onClick={() => void startNewChat()}>
            <Icon><path d="M12 21a9 9 0 1 0-8.2-5.3L3 21l5.3-.8A9 9 0 0 0 12 21Z" /><path d="M12 8v8M8 12h8" /></Icon>
            新对话
          </button>
          <button className="nav-item" onClick={() => setSearchOpen((value) => !value)}>
            <Icon><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></Icon>
            搜索对话
          </button>
          {searchOpen ? (
            <input
              aria-label="搜索最近对话"
              className="conversation-search"
              onChange={(event) => setSearch(event.target.value)}
              placeholder="输入会话关键词"
              value={search}
            />
          ) : null}
          <button className="nav-item" onClick={() => void openLibrary()}>
            <Icon><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H10l2 2h5.5A2.5 2.5 0 0 1 20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5Z" /></Icon>
            文件库
          </button>
        </nav>

        <div className="sidebar-section">
          <p className="sidebar-label">最近对话</p>
          <ConversationList
            conversations={visibleConversations}
            onDelete={(id, title) => void deleteConversation(id, title)}
            onSelect={(id) => void loadConversation(id)}
            selectedId={selectedConversation}
          />
        </div>
        <div className="sidebar-footer">
          <button
            className={modelSettingsOpen ? "nav-item nav-item-active" : "nav-item"}
            onClick={() => {
              setLibraryOpen(false);
              setModelSettingsOpen(true);
            }}
          >
            <Icon><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.8 1.8 0 0 0 .4 2l.1.1-2.8 2.8-.1-.1a1.8 1.8 0 0 0-2-.4 1.8 1.8 0 0 0-1.1 1.7V21h-4v-.1A1.8 1.8 0 0 0 8.8 19a1.8 1.8 0 0 0-2 .4l-.1.1-2.8-2.8.1-.1a1.8 1.8 0 0 0 .4-2A1.8 1.8 0 0 0 2.7 13H2V9h.7a1.8 1.8 0 0 0 1.7-1.1 1.8 1.8 0 0 0-.4-2l-.1-.1L6.7 3l.1.1a1.8 1.8 0 0 0 2 .4A1.8 1.8 0 0 0 9.9 2H14v.1a1.8 1.8 0 0 0 1.1 1.7 1.8 1.8 0 0 0 2-.4l.1-.1L20 6.1l-.1.1a1.8 1.8 0 0 0-.4 2A1.8 1.8 0 0 0 21.2 9h.8v4h-.8a1.8 1.8 0 0 0-1.8 2Z" /></Icon>
            模型配置
          </button>
        </div>
      </aside>

      <main className="chat-surface">
        {modelSettingsOpen ? (
          <ModelProfileManager onBack={() => setModelSettingsOpen(false)} />
        ) : libraryOpen ? (
          <section className="library-panel" aria-label="文件库">
            <div className="panel-heading">
              <div><h1>文件库</h1><p>当前本地工作区已上传的论文</p></div>
              <button onClick={() => setLibraryOpen(false)}>返回对话</button>
            </div>
            <div className="file-grid">
              {libraryFiles.map((file) => (
                <article className="library-file" key={file.id}>
                  <strong>{file.name}</strong>
                  <span>{Math.ceil(file.size_bytes / 1024)} KB</span>
                  <small>{file.parse_status}</small>
                </article>
              ))}
              {libraryFiles.length === 0 ? <p>还没有上传文件。</p> : null}
            </div>
          </section>
        ) : messages.length === 0 ? (
          <section className="welcome-panel" aria-labelledby="welcome-title">
            <div className="welcome-symbol">P</div>
            <h1 id="welcome-title">准备好了，随时开始</h1>
            <p>阅读论文、比较研究、整理证据或协助学术写作</p>
          </section>
        ) : (
          <section className="conversation-surface" aria-label="当前对话">
            {messages.map((message) =>
              message.role === "assistant" ? (
                <AssistantMessage key={message.id} message={message} />
              ) : (
                <div className="chat-message-user" key={message.id}>
                  {message.content}
                </div>
              ),
            )}
          </section>
        )}

        {!libraryOpen && !modelSettingsOpen ? (
          <div className="composer-dock">
            {files.length ? (
              <div className="attached-files" aria-label="已上传文件">
                {files.map((file) => (
                  <span key={file.id}>
                    <span className="attached-file-name">{file.name}</span>
                    <small>{file.parse_status}</small>
                    <button
                      className="file-debug-button"
                      disabled={diagnosticLoading || file.parse_status === "uploading"}
                      onClick={() => void openParseDiagnostics(file)}
                      type="button"
                    >
                      解析
                    </button>
                  </span>
                ))}
                <button
                  className="diagnostic-toggle"
                  onClick={() => setDiagnosticOpen((value) => !value)}
                  type="button"
                >
                  检索诊断
                </button>
              </div>
            ) : null}
            {diagnosticOpen ? (
              <section className="diagnostic-panel" aria-label="检索和解析诊断">
                <div className="diagnostic-panel-header">
                  <strong>调试面板</strong>
                  <button onClick={() => setDiagnosticOpen(false)} type="button">关闭</button>
                </div>
                <div className="retrieval-debug-form">
                  <input
                    aria-label="检索诊断问题"
                    onChange={(event) => setRetrievalQuestion(event.target.value)}
                    placeholder="输入问题，查看每一步召回结果"
                    value={retrievalQuestion}
                  />
                  <button
                    disabled={diagnosticLoading}
                    onClick={() => void runRetrievalDiagnostics()}
                    type="button"
                  >
                    运行
                  </button>
                </div>
                {diagnosticLoading ? <p className="diagnostic-empty">正在读取诊断结果...</p> : null}
                {parseResult ? (
                  <div className="parse-debug-view">
                    <div className="diagnostic-section-list">
                      <h4>章节树</h4>
                      {parseResult.sections.map((section) => (
                        <button
                          className={selectedDebugSection === section.section_id ? "selected" : ""}
                          key={section.id}
                          onClick={() => setSelectedDebugSection(section.section_id)}
                          style={{ paddingLeft: `${8 + Math.max(0, section.level - 1) * 12}px` }}
                          type="button"
                        >
                          {section.number ? `${section.number} ` : ""}{section.title}
                          <small>p{section.page_start}-{section.page_end}</small>
                        </button>
                      ))}
                      {parseResult.sections.length === 0 ? <p className="diagnostic-empty">未识别章节</p> : null}
                    </div>
                    <div className="diagnostic-chunk-list">
                      <h4>Chunks</h4>
                      {parseResult.chunks
                        .filter((chunk) => !selectedDebugSection || chunk.section_id === selectedDebugSection)
                        .map((chunk) => (
                          <article className="diagnostic-hit" key={chunk.chunk_id}>
                            <header>
                              <strong>{chunk.section_path.join(" / ") || chunk.section_title || "未识别章节"}</strong>
                              <span>p{chunk.page_start}-{chunk.page_end} · chunk {chunk.chunk_index_in_section}</span>
                            </header>
                            <p>{chunk.text}</p>
                          </article>
                        ))}
                    </div>
                  </div>
                ) : null}
                {retrievalPreview ? (
                  <div className="retrieval-debug-view">
                    <p className="diagnostic-summary">
                      Section hint: {retrievalPreview.parsed_section_hint || "未识别"}
                    </p>
                    {(() => {
                      const finalIds = new Set(
                        retrievalPreview.final_context_sent_to_llm.map((hit) => hit.chunk_id),
                      );
                      return (
                        <>
                          <RetrievalStage title="Exact" hits={retrievalPreview.exact_match_hits} finalIds={finalIds} />
                          <RetrievalStage title="Section" hits={retrievalPreview.section_hits} finalIds={finalIds} />
                          <RetrievalStage title="Vector" hits={retrievalPreview.vector_hits} finalIds={finalIds} />
                          <RetrievalStage title="BM25" hits={retrievalPreview.bm25_hits} finalIds={finalIds} />
                          <RetrievalStage title="Merged" hits={retrievalPreview.merged_hits} finalIds={finalIds} />
                          <RetrievalStage title="Rerank / Final" hits={retrievalPreview.reranked_hits} finalIds={finalIds} />
                        </>
                      );
                    })()}
                  </div>
                ) : null}
              </section>
            ) : null}
            <input
              ref={fileInputRef}
              className="visually-hidden"
              type="file"
              accept=".pdf,application/pdf"
              aria-label="上传论文或文档"
              onChange={(event) => void upload(event)}
            />
            <MessageComposer
              disabled={busy}
              onAttach={() => fileInputRef.current?.click()}
              onSubmit={(content) => void submit(content)}
            />
            {status && activeTaskId ? (
              <TaskStatusMonitor
                status={status}
                events={taskEvents}
                logPath={taskLogPath}
                onOpen={refreshActiveTaskMonitor}
              />
            ) : status ? (
              <p className="task-status">{status}</p>
            ) : null}
            {error ? <p className="task-error">{error}</p> : null}
            <p className="composer-note">PaperAgent 可能会出错，请核对重要事实和引用。</p>
          </div>
        ) : null}
      </main>
      <aside className={usageOpen ? "usage-panel" : "usage-panel collapsed"}>
        <button
          aria-label={usageOpen ? "折叠 Token 用量" : "展开 Token 用量"}
          className="usage-toggle"
          onClick={() => setUsageOpen((value) => !value)}
        >
          {usageOpen ? "›" : "‹"}
        </button>
        {usageOpen ? (
          <div className="usage-content">
            <h2>Token 用量</h2>
            <p>当前会话 · 实时更新</p>
            {(["small", "large"] as const).map((role) => (
              <section key={role}>
                <strong>{role === "small" ? "小模型" : "大模型"}</strong>
                <dl>
                  <div><dt>读入</dt><dd>{usage[role].input_tokens.toLocaleString()}</dd></div>
                  <div><dt>写出</dt><dd>{usage[role].output_tokens.toLocaleString()}</dd></div>
                  <div><dt>合计</dt><dd>{usage[role].total_tokens.toLocaleString()}</dd></div>
                </dl>
              </section>
            ))}
            <section className="usage-total">
              <strong>总用量</strong>
              <b>{usage.total.total_tokens.toLocaleString()}</b>
              <small>
                读入 {usage.total.input_tokens.toLocaleString()} · 写出{" "}
                {usage.total.output_tokens.toLocaleString()}
              </small>
            </section>
          </div>
        ) : null}
      </aside>
    </div>
  );
};
