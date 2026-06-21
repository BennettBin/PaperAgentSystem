import React from "react";

export interface ArtifactCardProps {
  artifact: {
    id: string;
    type: string;
    title: string;
    content: string;
  };
}

export const ArtifactCard: React.FC<ArtifactCardProps> = ({ artifact }) => {
  return (
    <div className="artifact-card" data-testid={`artifact-${artifact.id}`}>
      <h3>{artifact.title}</h3>
      <p className="artifact-type">{artifact.type}</p>
      <div className="artifact-content">{artifact.content}</div>
    </div>
  );
};
