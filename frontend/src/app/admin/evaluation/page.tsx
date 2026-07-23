"use client";

import { FormEvent, useState } from "react";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api/v1";

interface Metric {
  value: number | null;
  numerator: number | null;
  denominator: number;
  unit: string;
  confidence_interval?: { lower: number; upper: number; confidence: number } | null;
  case_ids: string[];
}

interface DashboardResponse {
  report_versions: string[];
  row_count: number;
  case_ids: string[];
  metrics: Record<string, Metric>;
}

interface CaseDetail {
  case_id: string;
  system_id: string;
  report_version: string;
  plan: Array<{ title: string; status: string }>;
  actions: Array<{ name: string; status: string }>;
  observations: Array<{ code: string; status: string }>;
  citations: Array<{ evidence_id: string; source_id: string; page: number }>;
  public_trace: Array<{ kind: string; title: string; status: string }>;
}

const LABELS: Record<string, string> = {
  task_success: "Task Success",
  claim_support: "Claim Support",
  total_tokens: "平均 Token",
  four_b_call_rate: "4B 调用率",
  p95_latency_ms: "P95 Latency",
  cost_per_success: "单位成功成本",
};

function display(metric: Metric): string {
  if (metric.value === null) return "N/A";
  if (metric.unit === "ratio" || metric.unit === "ratio_of_model_calls") {
    return `${(metric.value * 100).toFixed(2)}%`;
  }
  if (metric.unit === "milliseconds") return `${metric.value.toFixed(0)} ms`;
  return metric.value.toFixed(2);
}

export default function EvaluationAdminPage() {
  const [token, setToken] = useState("");
  const [filters, setFilters] = useState({
    task_family: "", difficulty: "", language: "", model: "",
    error_category: "", system_id: "b3_full_4b",
  });
  const [dashboard, setDashboard] = useState<DashboardResponse | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [error, setError] = useState("");

  const loadMetrics = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setDetail(null);
    const query = new URLSearchParams(
      Object.entries(filters).filter(([, value]) => Boolean(value)),
    );
    const response = await fetch(`${API_BASE}/admin/evaluation/metrics?${query}`, {
      headers: { "X-Admin-Token": token },
    });
    if (!response.ok) {
      setError(response.status === 401 ? "管理员凭证无效" : "评测报告不可用");
      return;
    }
    setDashboard((await response.json()) as DashboardResponse);
  };

  const loadCase = async (caseId: string) => {
    const response = await fetch(
      `${API_BASE}/admin/evaluation/cases/${encodeURIComponent(filters.system_id)}/${encodeURIComponent(caseId)}`,
      { headers: { "X-Admin-Token": token } },
    );
    if (response.ok) setDetail((await response.json()) as CaseDetail);
  };

  return (
    <main style={{ maxWidth: 1180, margin: "0 auto", padding: "36px 24px", color: "#172033" }}>
      <header style={{ marginBottom: 28 }}>
        <p style={{ color: "#50607a", margin: 0 }}>PaperAgent · Admin only</p>
        <h1 style={{ fontSize: 32, margin: "8px 0" }}>Evaluation Dashboard</h1>
        <p style={{ color: "#64748b" }}>仅展示版本化离线报告、公开轨迹摘要与证据定位；不展示论文正文或隐藏推理。</p>
      </header>

      <form onSubmit={loadMetrics} style={{ display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))", gap: 12, padding: 18, border: "1px solid #dbe3ef", borderRadius: 14 }}>
        <input aria-label="管理员凭证" type="password" placeholder="Admin token" value={token} onChange={(event) => setToken(event.target.value)} />
        {Object.entries(filters).map(([name, value]) => (
          <input key={name} aria-label={name} placeholder={name} value={value} onChange={(event) => setFilters((current) => ({ ...current, [name]: event.target.value }))} />
        ))}
        <button type="submit">加载冻结报告</button>
      </form>

      {error && <p role="alert" style={{ color: "#b42318" }}>{error}</p>}
      {dashboard && (
        <>
          <p style={{ color: "#64748b" }}>Report: {dashboard.report_versions.join(", ")} · N={dashboard.row_count}</p>
          <section style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: 14 }}>
            {Object.entries(dashboard.metrics).map(([name, metric]) => (
              <article key={name} style={{ border: "1px solid #dbe3ef", borderRadius: 14, padding: 18, background: "#fff" }}>
                <span style={{ color: "#64748b" }}>{LABELS[name] ?? name}</span>
                <strong style={{ display: "block", fontSize: 28, margin: "8px 0" }}>{display(metric)}</strong>
                <small>分母 {metric.denominator}{metric.confidence_interval ? ` · 95% CI [${metric.confidence_interval.lower.toFixed(3)}, ${metric.confidence_interval.upper.toFixed(3)}]` : ""}</small>
                <button type="button" onClick={() => metric.case_ids[0] && loadCase(metric.case_ids[0])} disabled={!metric.case_ids.length} style={{ display: "block", marginTop: 12 }}>下钻首个样本</button>
              </article>
            ))}
          </section>
        </>
      )}

      {detail && (
        <section style={{ marginTop: 24, border: "1px solid #dbe3ef", borderRadius: 14, padding: 20 }}>
          <h2>公开样本下钻 · {detail.case_id}</h2>
          <p>System: {detail.system_id} · Report: {detail.report_version}</p>
          <h3>Plan</h3><ul>{detail.plan.map((item, index) => <li key={index}>{item.title} · {item.status}</li>)}</ul>
          <h3>Actions / Observations</h3><ul>{detail.actions.map((item, index) => <li key={`a-${index}`}>{item.name} · {item.status}</li>)}{detail.observations.map((item, index) => <li key={`o-${index}`}>{item.code} · {item.status}</li>)}</ul>
          <h3>Citations</h3><ul>{detail.citations.map((item) => <li key={item.evidence_id}>{item.evidence_id} · {item.source_id} · p.{item.page}</li>)}</ul>
          <h3>Public Trace</h3><ul>{detail.public_trace.map((item, index) => <li key={index}>{item.title} · {item.status}</li>)}</ul>
        </section>
      )}
    </main>
  );
}
