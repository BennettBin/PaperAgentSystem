import React, { useState } from "react";

export interface MessageComposerProps {
  onSubmit: (content: string) => void;
  disabled?: boolean;
}

export const MessageComposer: React.FC<MessageComposerProps> = ({
  onSubmit,
  disabled = false,
}) => {
  const [content, setContent] = useState("");

  const handleSubmit = () => {
    if (content.trim()) {
      onSubmit(content);
      setContent("");
    }
  };

  return (
    <div className="message-composer">
      <textarea
        value={content}
        onChange={(e) => setContent(e.target.value)}
        placeholder="Type your message..."
        disabled={disabled}
        data-testid="message-input"
      />
      <button onClick={handleSubmit} disabled={disabled || !content.trim()}>
        Send
      </button>
    </div>
  );
};
