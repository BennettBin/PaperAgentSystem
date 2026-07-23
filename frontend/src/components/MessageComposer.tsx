import React, { useState } from "react";

export interface MessageComposerProps {
  onSubmit: (content: string) => void;
  onAttach?: () => void;
  disabled?: boolean;
}

export const MessageComposer: React.FC<MessageComposerProps> = ({
  onSubmit,
  onAttach,
  disabled = false,
}) => {
  const [content, setContent] = useState("");

  const submit = () => {
    if (!disabled && content.trim()) {
      onSubmit(content.trim());
      setContent("");
    }
  };

  return (
    <div className="message-composer">
      <button aria-label="添加文件" className="composer-icon-button" onClick={onAttach} type="button">
        <svg aria-hidden="true" height="21" viewBox="0 0 24 24" width="21">
          <path d="M12 5v14M5 12h14" />
        </svg>
        <span>上传论文</span>
      </button>
      <textarea
        aria-label="消息"
        data-testid="message-input"
        disabled={disabled}
        onChange={(event) => setContent(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder="询问论文、上传材料或开始写作"
        rows={1}
        value={content}
      />
      <button
        aria-label="发送消息"
        className="send-button"
        disabled={disabled || !content.trim()}
        onClick={submit}
        type="button"
      >
        <svg aria-hidden="true" height="18" viewBox="0 0 24 24" width="18">
          <path d="M12 19V5M6 11l6-6 6 6" />
        </svg>
      </button>
    </div>
  );
};
