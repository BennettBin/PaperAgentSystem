import React from "react";
import { describe, it, expect, vi } from "vitest";
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

describe("Frontend Components", () => {
  it("renders ConversationList", () => {
    const conversations = [
      { id: "1", title: "Test", created_at: "2026-06-19T00:00:00Z", message_count: 5 },
    ];
    render(<ConversationList conversations={conversations} onSelect={() => {}} />);
    expect(screen.getByText("Conversations")).toBeDefined();
  });

  it("switches conversations and filters the list", () => {
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
    fireEvent.change(screen.getByPlaceholderText("Search conversations..."), {
      target: { value: "Beta" },
    });
    expect(screen.queryByText("Alpha paper")).toBeNull();
    fireEvent.click(screen.getByText("Beta paper"));
    expect(onSelect).toHaveBeenCalledWith("2");
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

  it("renders ModelProfileManager in development", () => {
    const profiles = [{ name: "dev", status: "active", context_length: 4096 }];
    render(<ModelProfileManager profiles={profiles} onSelect={() => {}} isDevelopment={true} />);
    expect(screen.getByTestId("model-profile-manager")).toBeDefined();
  });

  it("hides ModelProfileManager in production", () => {
    const profiles = [{ name: "dev", status: "active", context_length: 4096 }];
    const { container } = render(<ModelProfileManager profiles={profiles} onSelect={() => {}} isDevelopment={false} />);
    expect(container.firstChild).toBe(null);
  });
});
