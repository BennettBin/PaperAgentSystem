import React, { useState } from "react";

export interface WorkspaceEntry {
  id: string;
  name: string;
  type: string;
  source?: string;
}

export interface WorkspacePanelProps {
  entries: WorkspaceEntry[];
  onPromote?: (entryId: string) => void;
  onDelete?: (entryId: string) => void;
}

export const WorkspacePanel: React.FC<WorkspacePanelProps> = ({
  entries,
  onPromote,
  onDelete,
}) => {
  const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

  return (
    <div className="workspace-panel">
      <h3>Workspace Files</h3>
      <ul>
        {entries.map((entry) => (
          <li key={entry.id} data-testid={`entry-${entry.id}`}>
            <span>{entry.name}</span>
            {entry.source && <small>{entry.source}</small>}
            {deleteConfirm === entry.id ? (
              <>
                <span>Confirm delete?</span>
                <button
                  onClick={() => {
                    onDelete?.(entry.id);
                    setDeleteConfirm(null);
                  }}
                >
                  Yes
                </button>
                <button onClick={() => setDeleteConfirm(null)}>No</button>
              </>
            ) : (
              <>
                {onPromote && (
                  <button onClick={() => onPromote(entry.id)}>Promote</button>
                )}
                {onDelete && (
                  <button onClick={() => setDeleteConfirm(entry.id)}>
                    Delete
                  </button>
                )}
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
};
