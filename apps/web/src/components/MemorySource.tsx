import React from "react";

export interface MemorySourceProps {
  segment: {
    id: string;
    content: string;
    source_messages: string[];
  };
}

export const MemorySource: React.FC<MemorySourceProps> = ({ segment }) => {
  return (
    <div className="memory-source" data-testid={`memory-${segment.id}`}>
      <p className="memory-content">{segment.content}</p>
      <small>Referenced from {segment.source_messages.length} message(s)</small>
    </div>
  );
};
