import React from "react";

export interface ConversationListProps {
  conversations: Array<{
    id: string;
    title: string;
    created_at: string;
    message_count: number;
  }>;
  onSelect: (id: string) => void;
}

export const ConversationList: React.FC<ConversationListProps> = ({
  conversations,
  onSelect,
}) => {
  const [query, setQuery] = React.useState("");
  const filtered = conversations.filter((conversation) =>
    conversation.title.toLowerCase().includes(query.toLowerCase()),
  );
  return (
    <div className="conversation-list">
      <h2>Conversations</h2>
      <input
        type="text"
        placeholder="Search conversations..."
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      <ul>
        {filtered.map((conv) => (
          <li key={conv.id}>
            <button type="button" onClick={() => onSelect(conv.id)}>
              <h3>{conv.title}</h3>
              <p>{conv.message_count} messages</p>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
};
