import React from "react";

export interface SettingsPageProps {}

export const SettingsPage: React.FC<SettingsPageProps> = () => {
  return (
    <div className="settings-page">
      <h2>Settings & Data Management</h2>
      <div className="settings-section">
        <h3>User Preferences</h3>
        <label>
          <input type="checkbox" defaultChecked /> Enable notifications
        </label>
      </div>
      <div className="settings-section">
        <h3>Data Management</h3>
        <button data-testid="export-data">Export All Data</button>
        <button data-testid="delete-data">Delete All Data</button>
      </div>
    </div>
  );
};
