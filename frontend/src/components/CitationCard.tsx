import React from "react";

export interface Citation {
  id: string;
  text: string;
  source_page: number;
  file_id: string;
}

export interface CitationCardProps {
  citation: Citation;
  collapsed?: boolean;
}

export const CitationCard: React.FC<CitationCardProps> = ({
  citation,
  collapsed = false,
}) => {
  const [open, setOpen] = React.useState(!collapsed);
  return (
    <div className="citation-card" data-testid={`citation-${citation.id}`}>
      <button
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {citation.id}
      </button>
      <span>第 {citation.source_page} 页</span>
      {open ? <p>{citation.text}</p> : null}
    </div>
  );
};
