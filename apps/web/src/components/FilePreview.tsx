import React from "react";

export interface FilePreviewProps {
  file: {
    id: string;
    name: string;
    type: string;
  };
  onClose: () => void;
}

export const FilePreview: React.FC<FilePreviewProps> = ({ file, onClose }) => {
  return (
    <div className="file-preview" data-testid={`preview-${file.id}`}>
      <div className="preview-header">
        <h3>{file.name}</h3>
        <button onClick={onClose}>Close</button>
      </div>
      <div className="preview-content">
        <p>Preview for {file.type} files would be displayed here</p>
      </div>
    </div>
  );
};
