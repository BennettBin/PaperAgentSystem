import React from "react";

export interface Citation {
  id: string;
  text: string;
  source_page: number;
  file_id: string;
}

export interface CitationCardProps {
  citation: Citation;
}

export const CitationCard: React.FC<CitationCardProps> = ({ citation }) => {
  return (
    <div className="citation-card" data-testid={`citation-${citation.id}`}>
      <a
        href={`#page-${citation.source_page}`}
        onClick={(e) => e.preventDefault()}
      >
        📄 Page {citation.source_page}
      </a>
      <p>{citation.text}</p>
    </div>
  );
};
