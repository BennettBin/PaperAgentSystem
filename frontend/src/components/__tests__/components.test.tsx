import React from "react";
import { beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ConversationList } from "../ConversationList";
import { MessageList } from "../MessageList";
import { MessageComposer } from "../MessageComposer";
import { AttachmentPicker } from "../AttachmentPicker";
import { CitationCard } from "../CitationCard";
import { FilePreview } from "../FilePreview";
import { ModelProfileManager } from "../ModelProfileManager";
import { AppLayout, AssistantMessage, TaskStatusMonitor } from "../AppLayout";

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
      } else if (url.includes("/usage")) {
        payload = {
          small: { input_tokens: 120, output_tokens: 20, total_tokens: 140 },
          large: { input_tokens: 500, output_tokens: 80, total_tokens: 580 },
          total: { input_tokens: 620, output_tokens: 100, total_tokens: 720 },
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

  it("deletes a conversation without selecting it", () => {
    const onSelect = vi.fn();
    const onDelete = vi.fn();
    render(
      <ConversationList
        conversations={[
          { id: "1", title: "Alpha paper", created_at: "", message_count: 1 },
        ]}
        onDelete={onDelete}
        onSelect={onSelect}
      />,
    );

    fireEvent.click(screen.getByLabelText("彻底删除会话 Alpha paper"));

    expect(onDelete).toHaveBeenCalledWith("1", "Alpha paper");
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("removes a deleted conversation from the app list", async () => {
    const confirmMock = vi.spyOn(window, "confirm").mockReturnValue(true);
    let listDeleted = false;
    fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      let payload: unknown = { items: [] };
      if (url.endsWith("/conversations") && init?.method !== "POST") {
        payload = {
          items: listDeleted
            ? []
            : [{ id: "delete-me", title: "Delete me", created_at: "", message_count: 0 }],
        };
      } else if (url.endsWith("/conversations/delete-me") && init?.method === "DELETE") {
        listDeleted = true;
        payload = { deleted: true, conversation_id: "delete-me", deleted_file_count: 0 };
      } else if (url.includes("/usage")) {
        payload = {
          small: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
          large: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
          total: { input_tokens: 0, output_tokens: 0, total_tokens: 0 },
        };
      }
      return { ok: true, json: async () => payload };
    });

    render(<AppLayout />);
    expect(await screen.findByText("Delete me")).toBeDefined();
    fireEvent.click(screen.getByLabelText("彻底删除会话 Delete me"));

    expect(await screen.findByText("历史会话和关联文件已彻底删除")).toBeDefined();
    expect(screen.queryByText("Delete me")).toBeNull();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/conversations/delete-me",
      { method: "DELETE" },
    );
    confirmMock.mockRestore();
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

  it("opens Agent progress monitoring beside the task status", () => {
    const onOpen = vi.fn();
    render(
      <TaskStatusMonitor
        status="正在执行 Agent 任务…"
        events={[
          {
            event_id: "plan-1",
            task_id: "task-1",
            sequence: 1,
            type: "plan_created",
            title: "已生成公开执行计划",
            data: {
              plan_id: "plan-task-1",
              goal: "总结论文方法",
              steps: [
                {
                  step_id: "retrieve",
                  title: "检索论文证据",
                  step_type: "tool_call",
                  depends_on: [],
                },
                {
                  step_id: "answer",
                  title: "生成并核验回答",
                  step_type: "generate",
                  depends_on: ["retrieve"],
                },
              ],
            },
            created_at: "2026-07-22T11:59:59Z",
          },
          {
            event_id: "plan-step-1",
            task_id: "task-1",
            sequence: 2,
            type: "plan_step_completed",
            title: "计划步骤完成：检索论文证据",
            data: { plan_id: "plan-task-1", step_id: "retrieve" },
            created_at: "2026-07-22T12:00:00Z",
          },
          {
            event_id: "event-1",
            task_id: "task-1",
            sequence: 3,
            type: "step_started",
            title: "小模型进行问题判断",
            data: {},
            created_at: "2026-07-22T12:00:00Z",
          },
          {
            event_id: "event-2",
            task_id: "task-1",
            sequence: 4,
            type: "skill_selected",
            title: "调用 summary_generator Skill",
            data: {
              skill_name: "summary_generator",
              skill_version: "1.0.0",
              model_profile: "development",
            },
            created_at: "2026-07-22T12:00:01Z",
          },
        ]}
        logPath="runtime/logs/agent/task-1.jsonl"
        onOpen={onOpen}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "监控" }));
    expect(screen.getByRole("dialog", { name: "Agent 任务监控" })).toBeDefined();
    expect(screen.getByText("小模型进行问题判断")).toBeDefined();
    expect(screen.getByText("调用 summary_generator Skill")).toBeDefined();
    expect(screen.getByRole("region", { name: "动态执行计划" })).toBeDefined();
    expect(screen.getByText("总结论文方法")).toBeDefined();
    expect(screen.getAllByText("检索论文证据").length).toBeGreaterThan(0);
    expect(screen.getByText("生成并核验回答")).toBeDefined();
    expect(screen.getByText("v1.0.0 · Profile: development")).toBeDefined();
    expect(screen.getByText("runtime/logs/agent/task-1.jsonl")).toBeDefined();
    expect(onOpen).toHaveBeenCalledTimes(1);
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

  it("shows a collapsible conversation token usage panel", async () => {
    render(<AppLayout />);
    expect(screen.getByText("Token 用量")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "折叠 Token 用量" }));
    expect(screen.queryByText("小模型")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "展开 Token 用量" }));
    expect(screen.getByText("小模型")).toBeDefined();
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

  it("renders CitationCard", () => {
    const citation = { id: "1", text: "Citation text", source_page: 5, file_id: "file-1" };
    render(<CitationCard citation={citation} />);
    expect(screen.getByTestId("citation-1")).toBeDefined();
  });

  it("expands citation text when the citation is clicked", () => {
    const citation = { id: "E1", text: "Quoted evidence", source_page: 5, file_id: "file-1" };
    render(<CitationCard citation={citation} collapsed />);
    expect(screen.queryByText("Quoted evidence")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "E1" }));
    expect(screen.getByText("Quoted evidence")).toBeDefined();
  });

  it("renders referenced figure, table, or algorithm screenshots with provenance", () => {
    render(
      <AssistantMessage
        message={{
          id: "assistant-visual",
          role: "assistant",
          content: "如 Table 1 所示 [E1]。",
          created_at: "2026-07-22T00:00:00Z",
          metadata: {
            evidence: [
              {
                id: "E1",
                file_id: "file-1",
                page: 3,
                section: ["Results"],
                quote: "The main result improves citation support.",
                bbox: [10, 20, 300, 200],
              },
            ],
            visual_artifacts: [
              {
                id: "file-1-p1-visual-1",
                kind: "table",
                label: "Table 1",
                caption: "Table 1: Main results",
                file_id: "file-1",
                page: 3,
                section: ["Results"],
                bbox: [10, 20, 300, 200],
                image_url: "/api/v1/visual-artifacts/file-1-p1-visual-1/image",
              },
            ],
          },
        }}
      />,
    );

    expect(screen.queryByText("The main result improves citation support.")).toBeNull();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "[E1]" }));
    expect(screen.getByText("The main result improves citation support.")).toBeDefined();
    fireEvent.mouseLeave(screen.getByTestId("inline-reference-E1"));

    expect(screen.queryByRole("img", { name: "Table 1，论文第 3 页" })).toBeNull();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "Table 1" }));
    expect(
      screen.getByRole("img", { name: "Table 1，论文第 3 页" }).getAttribute("src"),
    ).toBe("/api/v1/visual-artifacts/file-1-p1-visual-1/image");
    expect(screen.getByText("Table 1: Main results")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Table 1" }));
    fireEvent.mouseLeave(screen.getByTestId("inline-reference-file-1-p1-visual-1"));
    expect(screen.getByRole("img", { name: "Table 1，论文第 3 页" })).toBeDefined();
  });

  it("opens only the hovered occurrence when a citation id is repeated", () => {
    render(
      <AssistantMessage
        message={{
          id: "assistant-repeated-citation",
          role: "assistant",
          content: "第一处结论 [E1]，第二处结论仍引用 [E1]。",
          created_at: "2026-07-25T00:00:00Z",
          metadata: {
            evidence: [
              {
                id: "E1",
                file_id: "file-1",
                page: 3,
                section: ["Results"],
                quote: "Only one citation popover should be visible.",
              },
            ],
          },
        }}
      />,
    );

    const repeatedCitations = screen.getAllByRole("button", { name: "[E1]" });
    expect(repeatedCitations).toHaveLength(2);

    fireEvent.mouseEnter(repeatedCitations[0]);
    expect(
      screen.getAllByText("Only one citation popover should be visible."),
    ).toHaveLength(1);

    fireEvent.mouseLeave(repeatedCitations[0].closest(".inline-reference-shell")!);
    fireEvent.mouseEnter(repeatedCitations[1]);
    expect(
      screen.getAllByText("Only one citation popover should be visible."),
    ).toHaveLength(1);
  });

  it("renders a Markdown paper comparison as a semantic table", () => {
    render(
      <AssistantMessage
        message={{
          id: "assistant-comparison-table",
          role: "assistant",
          content: [
            "两篇论文对比如下：",
            "",
            "| 论文 | 方法 | 结果 |",
            "| --- | --- | --- |",
            "| Alpha | CNN [E1] | 90% |",
            "| Beta | Transformer [E2] | 92% |",
          ].join("\n"),
          created_at: "2026-07-25T00:00:00Z",
          metadata: {
            evidence: [
              {
                id: "E1",
                file_id: "file-alpha",
                page: 4,
                section: ["Method"],
                quote: "Alpha uses CNN.",
              },
              {
                id: "E2",
                file_id: "file-beta",
                page: 5,
                section: ["Method"],
                quote: "Beta uses Transformer.",
              },
            ],
          },
        }}
      />,
    );

    expect(screen.getByRole("table", { name: "论文对比表" })).toBeDefined();
    expect(screen.getByRole("columnheader", { name: "论文" })).toBeDefined();
    expect(screen.getByRole("cell", { name: "Alpha" })).toBeDefined();
    expect(screen.getByRole("cell", { name: "Transformer [E2]" })).toBeDefined();
    expect(screen.queryByText("| --- | --- | --- |")).toBeNull();
  });

  it("renders FilePreview", () => {
    const file = { id: "1", name: "test.pdf", type: "pdf" };
    render(<FilePreview file={file} onClose={() => {}} />);
    expect(screen.getByTestId("preview-1")).toBeDefined();
  });

  it("renders ModelProfileManager as a user-facing page", async () => {
    render(<ModelProfileManager onBack={() => {}} />);
    expect(screen.getByTestId("model-profile-manager")).toBeDefined();
    expect(await screen.findByText("小模型（1.7B）")).toBeDefined();
  });
});
