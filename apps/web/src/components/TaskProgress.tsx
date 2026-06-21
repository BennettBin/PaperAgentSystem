import React from "react";

export interface TaskProgressProps {
  task: {
    id: string;
    title: string;
    status: "pending" | "running" | "completed" | "failed";
    progress: number;
  };
}

export const TaskProgress: React.FC<TaskProgressProps> = ({ task }) => {
  return (
    <div
      className="task-progress"
      data-testid={`task-progress-${task.id}`}
    >
      <h4>{task.title}</h4>
      <div className="progress-bar">
        <div
          className="progress-fill"
          style={{ width: `${task.progress}%` }}
          data-testid={`progress-fill-${task.id}`}
        />
      </div>
      <span>{task.progress}%</span>
      <p>Status: {task.status}</p>
    </div>
  );
};
