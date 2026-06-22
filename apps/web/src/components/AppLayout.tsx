"use client";

import React from "react";

import {
  ChatMessage,
  ConversationSummary,
  PaperFile,
  paperApi,
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
  const [error, setError] = React.useState("");
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

  const loadConversation = React.useCallback(async (id: string) => {
    setError("");
    try {
      const detail = await paperApi.conversation(id);
      setSelectedConversation(id);
      setMessages(detail.messages);
      setFiles(detail.files);
      setLibraryOpen(false);
      setModelSettingsOpen(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "加载会话失败");
    }
  }, []);

  const startNewChat = async () => {
    setBusy(true);
    setError("");
    try {
      const conversation = await paperApi.createConversation();
      setConversations((current) => [conversation, ...current]);
      setSelectedConversation(conversation.id);
      setMessages([]);
      setFiles([]);
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
    for (let attempt = 0; attempt < 180; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (!mountedRef.current) return;
      const task = await paperApi.task(taskId);
      if (task.status === "completed") {
        setStatus("回答已生成");
        await loadConversation(conversationId);
        await refreshConversations();
        return;
      }
      if (task.status === "failed" || task.status === "cancelled") {
        throw new Error(task.error ?? `任务${task.status}`);
      }
      setStatus(task.status === "running" ? "正在解析论文、检索证据并调用模型…" : "任务排队中…");
    }
    throw new Error("任务等待超时");
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

  const visibleConversations = conversations.filter((conversation) =>
    (conversation.title ?? "").toLocaleLowerCase().includes(search.toLocaleLowerCase()),
  );

  return (
    <div className="app-shell">
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
            {messages.map((message) => (
              <div
                className={message.role === "assistant" ? "chat-message-assistant" : "chat-message-user"}
                key={message.id}
              >
                {message.content}
              </div>
            ))}
          </section>
        )}

        {!libraryOpen && !modelSettingsOpen ? (
          <div className="composer-dock">
            {files.length ? (
              <div className="attached-files" aria-label="已上传文件">
                {files.map((file) => (
                  <span key={file.id}>
                    {file.name}
                    <small>{file.parse_status}</small>
                  </span>
                ))}
              </div>
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
            {status ? <p className="task-status">{status}</p> : null}
            {error ? <p className="task-error">{error}</p> : null}
            <p className="composer-note">PaperAgent 可能会出错，请核对重要事实和引用。</p>
          </div>
        ) : null}
      </main>
    </div>
  );
};
