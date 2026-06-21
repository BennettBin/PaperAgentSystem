import React from "react";

export interface ModelProfile {
  name: string;
  status: string;
  context_length: number;
}

export interface ModelProfileManagerProps {
  profiles: ModelProfile[];
  onSelect: (profileName: string) => void;
  isDevelopment?: boolean;
}

export const ModelProfileManager: React.FC<ModelProfileManagerProps> = ({
  profiles,
  onSelect,
  isDevelopment = process.env.NODE_ENV === "development",
}) => {
  if (!isDevelopment) {
    return null;
  }

  return (
    <div className="model-profile-manager" data-testid="model-profile-manager">
      <h3>Model Profiles (Dev Only)</h3>
      <select
        onChange={(e) => onSelect(e.target.value)}
        data-testid="profile-selector"
      >
        <option value="">Select a profile</option>
        {profiles.map((profile) => (
          <option key={profile.name} value={profile.name}>
            {profile.name} ({profile.status})
          </option>
        ))}
      </select>
    </div>
  );
};
