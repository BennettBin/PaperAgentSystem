import React from "react";

export interface ConversationListProps {
  conversations: Array<{
    id: string;
    title: string;
    created_at: string;
    message_count: number;
  }>;
  onSelect: (id: string) => void;
  selectedId?: string | null;
}

export const ConversationList: React.FC<ConversationListProps> = ({
  conversations,
  onSelect,
  selectedId,
}) => (
  <div className="conversation-list">
    <ul>
      {conversations.map((conversation) => (
        <li key={conversation.id}>
          <button
            className={selectedId === conversation.id ? "selected" : undefined}
            onClick={() => onSelect(conversation.id)}
            type="button"
          >
            <span>{conversation.title}</span>
          </button>
        </li>
      ))}
    </ul>
  </div>
);
