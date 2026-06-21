# ADR-0009: 系统与训练解耦

**状态**: 已接受  
**日期**: 2026-06-19

## 背景

系统需要支持模型微调（SFT/RL），但：

- 训练数据和代码应与运行时系统分离
- 基础模型应能独立运行
- 用户私有数据不应自动进入训练集
- Adapter 版本应可追踪和回滚

## 决策

明确分离：

```
运行时系统 (core + apps + infrastructure)
  └─ 引用 Model Profile（不包含权重路径）
  └─ 通过 Model Registry 查询

训练系统 (training/)
  ├─ 数据准备 (数据导出、清洗)
  ├─ 训练脚本 (Transformers + PEFT + TRL)
  ├─ 评测脚本 (指标计算)
  └─ Adapter 输出 (权重文件、Manifest)

模型存储 (models/)
  ├─ Base 模型 Manifest
  ├─ SFT/RL Adapter Manifest
  ├─ Profile 定义 (version 指向 Adapter)
  └─ 不存储权重（仅路径 + 元数据）
```

**规则**:

- 运行时系统无法导入 training/
- 训练代码只读取导出数据和 Schema
- 每个 Adapter 独立有 Manifest 和性能报告
- Profile 切换不需重启系统

## 替代方案

1. **训练代码混入运行时**: 缺点是耦合紧、部署复杂。
2. **完全分离的训练服务**: 缺点是多个系统难运维。

## 后果

### 优点

- ✅ 系统无任何强制训练依赖
- ✅ 可独立验证 Adapter 质量
- ✅ 用户私有数据默认不进训练
- ✅ 支持快速切换 Adapter

### 缺点

- ⚠️ 数据导出需要额外流程
- ⚠️ Adapter 评测需要独立运行
- ⚠️ 需要文档和工具支持

## 不变量

1. 运行时系统不导入 training/ 中的代码
2. 训练数据导出前必须获得明确同意
3. 用户会话数据不自动进入训练集
4. Adapter 晋级需要通过固定评测集

## 验收标准

- [ ] 无 training/ 依赖，系统可独立运行
- [ ] Adapter 版本追踪完整
- [ ] Profile 切换测试通过
- [ ] 用户数据默认不在训练集中
