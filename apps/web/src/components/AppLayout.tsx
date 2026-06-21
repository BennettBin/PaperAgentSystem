"use client";

import React from "react";

import { mockConversations } from "../lib/mock-data";
import { ConversationList } from "./ConversationList";
import { MessageComposer } from "./MessageComposer";

const Icon = ({ children, size = 20 }: { children: React.ReactNode; size?: number }) => (
  <svg aria-hidden="true" className="icon" height={size} viewBox="0 0 24 24" width={size}>
    {children}
  </svg>
);

export interface AppLayoutProps {}

export const AppLayout: React.FC<AppLayoutProps> = () => {
  const [selectedConversation, setSelectedConversation] = React.useState<string | null>(null);
  const [messages, setMessages] = React.useState<string[]>([]);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const startNewChat = () => {
    setSelectedConversation(null);
    setMessages([]);
  };

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="brand-row">
          <div className="brand-mark">P</div>
          <span>PaperAgent</span>
          <button className="icon-button sidebar-collapse" aria-label="收起侧边栏">
            <Icon size={18}>
              <rect height="16" rx="3" width="18" x="3" y="4" />
              <path d="M9 4v16" />
            </Icon>
          </button>
        </div>

        <nav className="primary-nav" aria-label="主要导航">
          <button className="nav-item nav-item-active" onClick={startNewChat}>
            <Icon>
              <path d="M12 21a9 9 0 1 0-8.2-5.3L3 21l5.3-.8A9 9 0 0 0 12 21Z" />
              <path d="M12 8v8M8 12h8" />
            </Icon>
            新对话
          </button>
          <button className="nav-item">
            <Icon><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></Icon>
            搜索对话
          </button>
          <button className="nav-item">
            <Icon><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H10l2 2h5.5A2.5 2.5 0 0 1 20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5Z" /></Icon>
            文件库
          </button>
        </nav>

        <div className="sidebar-section">
          <p className="sidebar-label">最近对话</p>
          <ConversationList
            conversations={mockConversations}
            onSelect={setSelectedConversation}
            selectedId={selectedConversation}
          />
        </div>

        <div className="sidebar-account">
          <span className="avatar">U</span>
          <span className="account-copy">
            <strong>本地用户</strong>
            <small>PaperAgent</small>
          </span>
          <button className="icon-button" aria-label="更多设置">
            <Icon size={18}>
              <circle cx="5" cy="12" r="1" />
              <circle cx="12" cy="12" r="1" />
              <circle cx="19" cy="12" r="1" />
            </Icon>
          </button>
        </div>
      </aside>

      <main className="chat-surface">
        {messages.length === 0 ? (
          <section className="welcome-panel" aria-labelledby="welcome-title">
            <div className="welcome-symbol">P</div>
            <h1 id="welcome-title">准备好了，随时开始</h1>
            <p>阅读论文、比较研究、整理证据或协助学术写作</p>
          </section>
        ) : (
          <section className="conversation-surface" aria-label="当前对话">
            {messages.map((message, index) => (
              <div className="chat-message-user" key={`${message}-${index}`}>
                {message}
              </div>
            ))}
          </section>
        )}

        <div className="composer-dock">
          <input
            ref={fileInputRef}
            className="visually-hidden"
            type="file"
            accept=".pdf,.docx,.txt,.md,.tex"
            aria-label="上传论文或文档"
          />
          <MessageComposer
            onAttach={() => fileInputRef.current?.click()}
            onSubmit={(content) => setMessages((current) => [...current, content])}
          />
          <div className="quick-actions" aria-label="快捷任务">
            <button onClick={() => fileInputRef.current?.click()}>
              <Icon size={17}><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H10l2 2h5.5A2.5 2.5 0 0 1 20 7.5v9A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5Z" /></Icon>
              上传论文
            </button>
            <button>
              <Icon size={17}><path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10Z" /><path d="m14 7 3 3" /></Icon>
              撰写或改写
            </button>
            <button>
              <Icon size={17}><circle cx="12" cy="12" r="9" /><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></Icon>
              检索文献
            </button>
          </div>
          <p className="composer-note">PaperAgent 可能会出错，请核对重要事实和引用。</p>
        </div>
      </main>
    </div>
  );
};
