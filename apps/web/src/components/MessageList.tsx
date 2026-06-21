import React from "react";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  type: string;
  created_at: string;
}

export interface MessageListProps {
  messages: readonly Message[];
}

export const MessageList: React.FC<MessageListProps> = ({ messages }) => {
  return (
    <div className="message-list">
      {messages.map((msg) => (
        <div
          key={msg.id}
          className={`message message-${msg.role}`}
          data-testid={`message-${msg.id}`}
        >
          <strong>{msg.role}:</strong>
          <p>{msg.content}</p>
        </div>
      ))}
    </div>
  );
};
