import React from "react";

export interface ClarificationQuestion {
  id: string;
  type: string;
  text: string;
  priority: string;
  is_required: boolean;
}

export interface ClarificationCardProps {
  questions: ClarificationQuestion[];
  onSubmit: (answers: Record<string, string>) => void;
}

export const ClarificationCard: React.FC<ClarificationCardProps> = ({
  questions,
  onSubmit,
}) => {
  const [answers, setAnswers] = React.useState<Record<string, string>>({});

  const handleSubmit = () => {
    onSubmit(answers);
  };

  return (
    <div className="clarification-card">
      <h3>Clarification Questions</h3>
      {questions.map((q) => (
        <div key={q.id} className="question">
          <label htmlFor={q.id}>{q.text}</label>
          <input
            id={q.id}
            type="text"
            placeholder="Your answer"
            onChange={(e) => setAnswers({ ...answers, [q.id]: e.target.value })}
            required={q.is_required}
            data-testid={`question-${q.id}`}
          />
        </div>
      ))}
      <button onClick={handleSubmit} data-testid="submit-clarification">
        Submit Answers
      </button>
    </div>
  );
};
