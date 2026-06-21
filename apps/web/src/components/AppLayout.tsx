"use client";

import React from "react";
import { ConversationList } from "./ConversationList";
import { MessageList } from "./MessageList";
import { MessageComposer } from "./MessageComposer";
import { AttachmentPicker } from "./AttachmentPicker";
import { ClarificationCard } from "./ClarificationCard";
import { TaskProgress } from "./TaskProgress";
import { CitationCard } from "./CitationCard";
import { ArtifactCard } from "./ArtifactCard";
import { WorkspacePanel } from "./WorkspacePanel";
import { FilePreview } from "./FilePreview";
import { MemorySource } from "./MemorySource";
import { SettingsPage } from "./SettingsPage";
import { ModelProfileManager } from "./ModelProfileManager";
import { mockConversations, mockMessages, mockTasks, mockArtifacts, mockMemorySegments } from "../lib/mock-data";
import { mockApi } from "../lib/mock-api";

export interface AppLayoutProps {}

export const AppLayout: React.FC<AppLayoutProps> = () => {
  const [selectedConv, setSelectedConv] = React.useState("conv-1");
  const [showSettings, setShowSettings] = React.useState(false);
  const [uploadStatus, setUploadStatus] = React.useState("No upload");
  const [clarificationStatus, setClarificationStatus] = React.useState("Pending");
  const workspaceEntries = [
    { id: "entry-1", name: "analysis.md", type: "markdown", source: "task-1" },
  ];

  return (
    <div className="app-layout">
      <header>
        <h1>PaperAgent</h1>
        <nav>
          <button onClick={() => setShowSettings(!showSettings)}>
            Settings
          </button>
        </nav>
      </header>

      {showSettings ? (
        <SettingsPage />
      ) : (
        <div className="main-content">
          <aside className="sidebar">
            <ConversationList
              conversations={mockConversations}
              onSelect={setSelectedConv}
            />
            <p data-testid="selected-conversation">{selectedConv}</p>
          </aside>

          <main className="content">
            <div className="message-area">
              <MessageList messages={mockMessages} />
              <ClarificationCard
                questions={[
                  {
                    id: "scope",
                    type: "scope",
                    text: "Which section should be analyzed?",
                    priority: "high",
                    is_required: true,
                  },
                ]}
                onSubmit={async (answers) => {
                  await mockApi.submitClarification(answers);
                  setClarificationStatus("Submitted");
                }}
              />
              <p data-testid="clarification-status">{clarificationStatus}</p>
              {mockTasks.map((task) => (
                <TaskProgress key={task.id} task={task} />
              ))}
            </div>

            <div className="composer-area">
              <AttachmentPicker
                onSelect={async (file) => {
                  setUploadStatus("Uploading");
                  await mockApi.upload(file);
                  setUploadStatus("Ready");
                }}
              />
              <p data-testid="upload-status">{uploadStatus}</p>
              <MessageComposer
                onSubmit={(content) => console.log(content)}
              />
            </div>

            <div className="widgets">
              {mockMemorySegments.map((segment) => (
                <MemorySource key={segment.id} segment={segment} />
              ))}
              {mockArtifacts.map((artifact) => (
                <ArtifactCard key={artifact.id} artifact={artifact} />
              ))}
              <CitationCard
                citation={{
                  id: "citation-1",
                  text: "Mock evidence excerpt",
                  source_page: 3,
                  file_id: "file-1",
                }}
              />
              <FilePreview
                file={{ id: "file-1", name: "paper.pdf", type: "pdf" }}
                onClose={() => undefined}
              />
            </div>
          </main>

          <aside className="right-sidebar">
            <WorkspacePanel
              entries={workspaceEntries}
              onPromote={() => undefined}
              onDelete={() => undefined}
            />
            <ModelProfileManager
              profiles={[
                { name: "development", status: "active", context_length: 4096 },
                { name: "evaluation", status: "inactive", context_length: 4096 },
              ]}
              onSelect={(profile) => console.log(profile)}
            />
          </aside>
        </div>
      )}
    </div>
  );
};
