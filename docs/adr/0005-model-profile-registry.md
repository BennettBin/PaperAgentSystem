# ADR-0005: Model Profile Registry

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

系统支持多种 LLM：

- 基础模型 (Qwen 1.7B/4B)
- SFT Adapter
- RL Adapter
- 不同的量化版本
- 开发/演示/生产环境不同配置

Skill、子 Agent 和系统不应硬编码模型路径。

## 决策

建立模型注册表 (Model Registry)：

- **Model Profile**: 不变的模型定义
  - `name`（如 `qwen3-1.7b-dev`）
  - `base_model`（如 `Qwen/Qwen2.5-1.7B`）
  - `adapter_paths`（SFT、RL、量化）
  - `context_length`
  - `temperature`、`top_p` 等超参
  - `status`: development / evaluation / production

- **Model Version**: 训练时的标识
  - `profile_id`
  - `commit_sha`
  - `metrics` (JSON)
  - `created_at`

- **Skill/SubAgent** 只引用 `profile_name`，不引用路径

## 替代方案

1. **硬编码路径**: 简单但不灵活。
2. **环境变量**: 可行但缺少版本管理。
3. **中央配置文件 (YAML)**: 需要重启才能切换。

## 后果

### 优点

- ✅ Skill/SubAgent 与模型解耦
- ✅ 支持无缝切换模型版本
- ✅ 训练结果可追踪到具体模型版本
- ✅ 支持 Fallback

### 缺点

- ⚠️ 需要额外的 Registry 查询
- ⚠️ 需要在训练后更新 Registry

## 不变量

1. Profile 一旦注册不能删除
2. 每个 Trace 必须记录使用的 Model Profile ID 和 Version
3. Skill 只能引用现存的 Profile
4. Profile 变化必须同步文档

## 验收标准

- [ ] Model Registry 实现完整
- [ ] Skill 定义可以引用 Profile
- [ ] Trace 包含模型版本信息
- [ ] Fallback 测试通过
