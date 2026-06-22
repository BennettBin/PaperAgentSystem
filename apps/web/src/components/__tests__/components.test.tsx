import React from "react";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConversationList } from "../ConversationList";
import { MessageList } from "../MessageList";
import { MessageComposer } from "../MessageComposer";
import { AttachmentPicker } from "../AttachmentPicker";
import { ClarificationCard } from "../ClarificationCard";
import { TaskProgress } from "../TaskProgress";
import { CitationCard } from "../CitationCard";
import { ArtifactCard } from "../ArtifactCard";
import { WorkspacePanel } from "../WorkspacePanel";
import { FilePreview } from "../FilePreview";
import { MemorySource } from "../MemorySource";
import { SettingsPage } from "../SettingsPage";
import { ModelProfileManager } from "../ModelProfileManager";
import { AppLayout } from "../AppLayout";

const fetchMock = vi.fn();
vi.stubGlobal("fetch", fetchMock);

describe("Frontend Components", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let payload: unknown = { items: [] };
      if (url.endsWith("/conversations") && init?.method === "POST") {
        payload = {
          id: "new-conversation",
          title: "新对话",
          created_at: "",
          message_count: 0,
        };
      } else if (url.includes("/files") && init?.method === "POST") {
        payload = {
          id: "file-1",
          name: "paper.pdf",
          content_type: "application/pdf",
          size_bytes: 10,
          created_at: "",
          parse_status: "queued",
          task_id: "parse-1",
        };
      } else if (url.includes("/messages") && init?.method === "POST") {
        payload = { task_id: "task-1", status: "queued" };
      } else if (url.includes("/product-tasks/")) {
        payload = { task_id: "task-1", status: "failed", error: "test stop" };
      } else if (url.endsWith("/model-settings")) {
        payload = {
          selected: {
            small: {
              model_id: "base-qwen3-1.7b",
              display_name: "Qwen3 1.7B Base",
              serving_model: "qwen3:1.7b",
              role: "small",
              stage: "base",
              installed: true,
              callable: true,
            },
            large: {
              model_id: "base-qwen3.5-4b",
              display_name: "Qwen3.5 4B Base",
              serving_model: "qwen3.5:4b",
              role: "large",
              stage: "base",
              installed: true,
              callable: true,
            },
          },
          models: [],
          ollama_available: true,
        };
      }
      return {
        ok: true,
        json: async () => payload,
      };
    });
  });
  it("renders ConversationList", () => {
    const conversations = [
      { id: "1", title: "Test", created_at: "2026-06-19T00:00:00Z", message_count: 5 },
    ];
    render(<ConversationList conversations={conversations} onSelect={() => {}} />);
    expect(screen.getByText("Test")).toBeDefined();
  });

  it("switches conversations", () => {
    const onSelect = vi.fn();
    render(
      <ConversationList
        conversations={[
          { id: "1", title: "Alpha paper", created_at: "", message_count: 1 },
          { id: "2", title: "Beta paper", created_at: "", message_count: 2 },
        ]}
        onSelect={onSelect}
      />,
    );
    fireEvent.click(screen.getByText("Beta paper"));
    expect(onSelect).toHaveBeenCalledWith("2");
  });

  it("renders a clean user home without development panels", () => {
    render(<AppLayout />);

    expect(screen.getByText("准备好了，随时开始")).toBeDefined();
    expect(screen.getByText("新对话")).toBeDefined();
    expect(screen.queryByText("Model Profiles (Dev Only)")).toBeNull();
    expect(screen.queryByText("Workspace Files")).toBeNull();
    expect(screen.queryByText("Clarification Questions")).toBeNull();
    expect(screen.queryByText("Analyzing paper content")).toBeNull();
  });

  it("submits a message from the clean composer", () => {
    render(<AppLayout />);
    fireEvent.change(screen.getByTestId("message-input"), {
      target: { value: "帮我总结这篇论文" },
    });
    fireEvent.click(screen.getByLabelText("发送消息"));

    expect(screen.getByText("帮我总结这篇论文")).toBeDefined();
    expect(screen.queryByText("准备好了，随时开始")).toBeNull();
  });

  it("opens conversation search and filters recent conversations", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        items: [
          { id: "1", title: "Alpha paper", created_at: "", message_count: 1 },
          { id: "2", title: "Beta methods", created_at: "", message_count: 2 },
        ],
      }),
    });
    render(<AppLayout />);
    fireEvent.click(screen.getByText("搜索对话"));
    const search = await screen.findByLabelText("搜索最近对话");
    fireEvent.change(search, { target: { value: "Beta" } });
    expect(screen.queryByText("Alpha paper")).toBeNull();
    expect(screen.getByText("Beta methods")).toBeDefined();
  });

  it("shows a selected uploaded file next to the composer", async () => {
    render(<AppLayout />);
    const input = screen.getByLabelText("上传论文或文档");
    const file = new File(["%PDF-test"], "paper.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    expect(await screen.findByText("paper.pdf")).toBeDefined();
    expect(screen.queryByText("撰写或改写")).toBeNull();
    expect(screen.queryByText("检索文献")).toBeNull();
  });

  it("opens the model configuration page from the sidebar footer", async () => {
    render(<AppLayout />);
    fireEvent.click(screen.getByText("模型配置"));
    expect(await screen.findByText("模型设置")).toBeDefined();
    expect(screen.getByText("小模型（1.7B）")).toBeDefined();
    expect(screen.getByText("大模型（4B）")).toBeDefined();
    expect(screen.getAllByText("Base").length).toBeGreaterThanOrEqual(2);
  });

  it("renders MessageList with messages", () => {
    const messages = [
      {
        id: "1",
        role: "user" as const,
        content: "Hello",
        type: "text",
        created_at: "2026-06-19T00:00:00Z",
      },
    ];
    render(<MessageList messages={messages} />);
    expect(screen.getByTestId("message-1")).toBeDefined();
  });

  it("renders MessageComposer", () => {
    render(<MessageComposer onSubmit={() => {}} />);
    expect(screen.getByTestId("message-input")).toBeDefined();
  });

  it("renders AttachmentPicker", () => {
    render(<AttachmentPicker onSelect={() => {}} />);
    expect(screen.getByTestId("file-input")).toBeDefined();
  });

  it("reports selected upload", () => {
    const onSelect = vi.fn();
    render(<AttachmentPicker onSelect={onSelect} />);
    const file = new File(["paper"], "paper.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByTestId("file-input"), { target: { files: [file] } });
    expect(onSelect).toHaveBeenCalledWith(file);
  });

  it("renders ClarificationCard with questions", () => {
    const questions = [
      { id: "1", type: "text", text: "What is your name?", priority: "high", is_required: true },
    ];
    render(<ClarificationCard questions={questions} onSubmit={() => {}} />);
    expect(screen.getByTestId("question-1")).toBeDefined();
  });

  it("submits clarification answers", () => {
    const onSubmit = vi.fn();
    render(
      <ClarificationCard
        questions={[{ id: "q1", type: "scope", text: "Scope?", priority: "high", is_required: true }]}
        onSubmit={onSubmit}
      />,
    );
    fireEvent.change(screen.getByTestId("question-q1"), { target: { value: "Methods" } });
    fireEvent.click(screen.getByTestId("submit-clarification"));
    expect(onSubmit).toHaveBeenCalledWith({ q1: "Methods" });
  });

  it("renders TaskProgress", () => {
    const task = { id: "1", title: "Test Task", status: "running" as const, progress: 50 };
    render(<TaskProgress task={task} />);
    expect(screen.getByTestId("task-progress-1")).toBeDefined();
  });

  it("renders CitationCard", () => {
    const citation = { id: "1", text: "Citation text", source_page: 5, file_id: "file-1" };
    render(<CitationCard citation={citation} />);
    expect(screen.getByTestId("citation-1")).toBeDefined();
  });

  it("renders ArtifactCard", () => {
    const artifact = { id: "1", type: "analysis", title: "Summary", content: "Content" };
    render(<ArtifactCard artifact={artifact} />);
    expect(screen.getByTestId("artifact-1")).toBeDefined();
  });

  it("renders WorkspacePanel", () => {
    render(<WorkspacePanel entries={[]} />);
    expect(screen.getByText("Workspace Files")).toBeDefined();
  });

  it("confirms workspace deletion and promotes entries", () => {
    const onDelete = vi.fn();
    const onPromote = vi.fn();
    render(
      <WorkspacePanel
        entries={[{ id: "entry-1", name: "draft.md", type: "markdown" }]}
        onDelete={onDelete}
        onPromote={onPromote}
      />,
    );
    fireEvent.click(screen.getByText("Promote"));
    expect(onPromote).toHaveBeenCalledWith("entry-1");
    fireEvent.click(screen.getByText("Delete"));
    fireEvent.click(screen.getByText("Yes"));
    expect(onDelete).toHaveBeenCalledWith("entry-1");
  });

  it("renders FilePreview", () => {
    const file = { id: "1", name: "test.pdf", type: "pdf" };
    render(<FilePreview file={file} onClose={() => {}} />);
    expect(screen.getByTestId("preview-1")).toBeDefined();
  });

  it("renders MemorySource", () => {
    const segment = { id: "1", content: "Memory content", source_messages: ["msg-1"] };
    render(<MemorySource segment={segment} />);
    expect(screen.getByTestId("memory-1")).toBeDefined();
  });

  it("renders SettingsPage", () => {
    render(<SettingsPage />);
    expect(screen.getByText("Settings & Data Management")).toBeDefined();
  });

  it("renders ModelProfileManager as a user-facing page", async () => {
    render(<ModelProfileManager onBack={() => {}} />);
    expect(screen.getByTestId("model-profile-manager")).toBeDefined();
    expect(await screen.findByText("小模型（1.7B）")).toBeDefined();
  });
});
