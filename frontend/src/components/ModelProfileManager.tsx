import React from "react";

import {
  ModelRole,
  ModelSettings,
  RuntimeModel,
  paperApi,
} from "../lib/api";

export interface ModelProfileManagerProps {
  onBack: () => void;
}

const roleCopy: Record<ModelRole, { title: string; description: string }> = {
  small: {
    title: "小模型（1.7B）",
    description: "用于需求理解、规划与轻量任务",
  },
  large: {
    title: "大模型（4B）",
    description: "用于论文证据综合与最终回答",
  },
};

const stageLabel = { base: "Base", sft: "SFT", rl: "RL" } as const;

export const ModelProfileManager: React.FC<ModelProfileManagerProps> = ({
  onBack,
}) => {
  const [settings, setSettings] = React.useState<ModelSettings | null>(null);
  const [custom, setCustom] = React.useState<Record<ModelRole, string>>({
    small: "",
    large: "",
  });
  const [busyRole, setBusyRole] = React.useState<ModelRole | null>(null);
  const [notice, setNotice] = React.useState("");
  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setError("");
    try {
      setSettings(await paperApi.modelSettings());
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型配置加载失败");
    }
  }, []);

  React.useEffect(() => {
    void load();
  }, [load]);

  const select = async (role: ModelRole, model: RuntimeModel) => {
    setBusyRole(role);
    setError("");
    setNotice(`正在验证 ${model.display_name}…`);
    try {
      setSettings(await paperApi.selectModel(role, model.model_id));
      setNotice(`已切换到 ${model.display_name}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型切换失败");
      setNotice("");
    } finally {
      setBusyRole(null);
    }
  };

  const useCustomBase = async (role: ModelRole) => {
    const modelName = custom[role].trim();
    if (!modelName) return;
    setBusyRole(role);
    setError("");
    setNotice(`正在检查 ${modelName} 是否可调用…`);
    try {
      const checked = await paperApi.checkModel(role, modelName);
      if (checked.requires_download) {
        setNotice(`${modelName} 尚未安装，正在自动下载；首次下载可能需要几分钟…`);
        setSettings(await paperApi.downloadModel(role, modelName));
      } else {
        setSettings(await paperApi.selectModel(role, checked.model_id));
      }
      setCustom((current) => ({ ...current, [role]: "" }));
      setNotice(`已验证并启用 ${modelName}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "模型检查或下载失败");
      setNotice("");
    } finally {
      setBusyRole(null);
    }
  };

  return (
    <section className="model-settings-page" data-testid="model-profile-manager">
      <div className="panel-heading">
        <div>
          <h1>模型设置</h1>
          <p>分别选择轻量模型和回答模型；默认使用未微调的 Base 版本。</p>
        </div>
        <button onClick={onBack}>返回对话</button>
      </div>

      {error ? <p className="settings-error">{error}</p> : null}
      {notice ? <p className="settings-notice">{notice}</p> : null}
      {!settings && !error ? <p className="settings-loading">正在读取本地模型服务…</p> : null}

      {settings ? (
        <div className="model-role-grid">
          {(["small", "large"] as const).map((role) => {
            const roleModels = settings.models.filter((model) => model.role === role);
            const selected = settings.selected[role];
            return (
              <article className="model-role-card" key={role}>
                <header>
                  <div>
                    <h2>{roleCopy[role].title}</h2>
                    <p>{roleCopy[role].description}</p>
                  </div>
                  <span className="selected-model-chip">{selected.display_name}</span>
                </header>

                {(["base", "sft", "rl"] as const).map((stage) => {
                  const versions = roleModels.filter((model) => model.stage === stage);
                  return (
                    <div className="model-stage" key={stage}>
                      <div className="model-stage-heading">
                        <strong>{stageLabel[stage]}</strong>
                        <span>
                          {stage === "base"
                            ? "原始模型"
                            : stage === "sft"
                              ? "监督微调版本"
                              : "强化学习版本"}
                        </span>
                      </div>
                      {versions.length ? (
                        versions.map((model) => {
                          const isSelected = selected.model_id === model.model_id;
                          return (
                            <button
                              className={`model-option${isSelected ? " selected" : ""}`}
                              disabled={busyRole === role}
                              key={model.model_id}
                              onClick={() => void select(role, model)}
                            >
                              <span>
                                <strong>{model.display_name}</strong>
                                <small>{model.serving_model} · {model.model_id}</small>
                              </span>
                              <span className={model.installed ? "model-ready" : "model-missing"}>
                                {isSelected ? "当前使用" : model.installed ? "可调用" : "需下载"}
                              </span>
                            </button>
                          );
                        })
                      ) : (
                        <p className="model-empty">尚未注册{stageLabel[stage]}版本</p>
                      )}
                    </div>
                  );
                })}

                <div className="custom-model-row">
                  <label htmlFor={`custom-${role}`}>使用其他 Ollama Base 模型</label>
                  <div>
                    <input
                      id={`custom-${role}`}
                      onChange={(event) =>
                        setCustom((current) => ({
                          ...current,
                          [role]: event.target.value,
                        }))
                      }
                      placeholder={role === "small" ? "例如 llama3.2:3b" : "例如 qwen3:4b"}
                      value={custom[role]}
                    />
                    <button
                      disabled={busyRole === role || !custom[role].trim()}
                      onClick={() => void useCustomBase(role)}
                    >
                      检查并使用
                    </button>
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
};
