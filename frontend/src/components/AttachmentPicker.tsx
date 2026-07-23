import React from "react";

export interface AttachmentPickerProps {
  onSelect: (file: File) => void;
  accept?: string;
}

export const AttachmentPicker: React.FC<AttachmentPickerProps> = ({
  onSelect,
  accept = ".pdf,.txt,.docx",
}) => {
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      onSelect(file);
    }
  };

  return (
    <div className="attachment-picker">
      <input
        type="file"
        accept={accept}
        onChange={handleFileSelect}
        data-testid="file-input"
      />
    </div>
  );
};
