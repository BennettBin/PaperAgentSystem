import React from "react";

export interface ConversationListProps {
  conversations: Array<{
    id: string;
    title: string;
    created_at: string;
    message_count: number;
  }>;
  onSelect: (id: string) => void;
  onDelete?: (id: string, title: string) => void;
  selectedId?: string | null;
}

export const ConversationList: React.FC<ConversationListProps> = ({
  conversations,
  onSelect,
  onDelete,
  selectedId,
}) => (
  <div className="conversation-list">
    <ul>
      {conversations.map((conversation) => (
        <li key={conversation.id}>
          <div className={selectedId === conversation.id ? "conversation-row selected" : "conversation-row"}>
            <button
              className="conversation-select"
              onClick={() => onSelect(conversation.id)}
              type="button"
            >
              <span>{conversation.title}</span>
            </button>
            {onDelete ? (
              <button
                aria-label={`彻底删除会话 ${conversation.title}`}
                className="conversation-delete"
                onClick={(event) => {
                  event.stopPropagation();
                  onDelete(conversation.id, conversation.title);
                }}
                title="彻底删除会话和关联文件"
                type="button"
              >
                ×
              </button>
            ) : null}
          </div>
        </li>
      ))}
    </ul>
  </div>
);
