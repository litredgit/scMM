# scMM 文档

本页只提供阅读路径和文档入口。项目概览见 [首页](../README.md)，
具体进展和历史验收见 [CHANGELOG](../CHANGELOG.md)，任务结束时的文档更新规则见
[AGENTS.md](../AGENTS.md#任务结束时的文档更新规则)。

当前使用行为、待办和历史证据分别维护；主题文档不重复维护阶段状态或测试数量。

## 开始使用

1. [安装与部署](installation.md)：uv 环境、RAW 外部依赖、服务器资源初始化、账号认证、网页启动和服务更新。
2. [管理员监控](workflow.md#管理员监控)：页面活动、任务与资源趋势，以及生产更新检查边界。
3. [工作流程](workflow.md)：Vue 六步项目与 Notebook，从输入到审核、分析和保存；[注释与同位素](workflow.md#注释与同位素)含规则和筛选导出。
4. 运行失败时查 [排错与调参](troubleshooting.md)，需要选择或解释参数时查 [参数参考](parameters.md)。

## 按需查阅

| 文档 | 内容 |
|---|---|
| [参数参考](parameters.md) | Notebook/API/CLI/网页默认值的区别、单位、算法阈值、评分规则 JSON/CSV 格式 |
| [Python API 与批处理](python-api.md) | 提取、变换、注释、合并、保存重载与 CLI 调用示例 |
| [分析](analysis.md) | 分析方法、不同分析入口、统计解释、轨迹与绘图、暂缓方法定义 |
| [数据与输出](data-output.md) | 数据模型、目录/文件格式、AnnData/H5AD 映射、项目快照和归档 |
| [脂质规则审阅草案](../rules/lipids/README.md) | 五类样本的可导入 JSON、分值对照、文献依据及适用边界；不自动启用 |
| [Thermo RAW 技术说明](thermo-raw.md) | reader 依赖与构建、流协议、精度边界、原始对照报告和复现 |

## 维护

- [代理工作指南](../AGENTS.md)：主要设计、模块职责及提问/提交规则；具体进展见 CHANGELOG。
- [开发指南](development.md)：模块职责、测试与发布、main/dev 环境分工、上游快照、开源敏感信息检查及历史清理计划。
- [待办与发展计划](roadmap.md)：工程完善与功能接入优先、可靠性与性能其次；真实验证待办已取消，公网开放已完成，见[当前顺序](roadmap.md#里程碑与依赖)；已通过验收的工作归 CHANGELOG。
- [改进审阅与执行交接](improvement-review.md)：2026-10-18 审阅证据，以及正确性、代码模块化、文档和前端的实施建议与验收要求；当前任务状态以 roadmap 为准。
- [CHANGELOG](../CHANGELOG.md)：实现、验证、验收和部署记录，包括历史环境证据。

## 新会话继续开发

按 [AGENTS.md](../AGENTS.md) → [roadmap 新会话起点](roadmap.md#新会话起点) →
[改进交接](improvement-review.md) → [前后端能力覆盖](development.md#前后端能力覆盖) → CHANGELOG 最新记录阅读。
2026-10-19 的 21 项需求已完成实现和本机验证，用户明确授权测试后自动发布；实际部署证据见 CHANGELOG。
后续从 roadmap 的剩余事项继续，不重新执行已完成功能及审阅修复。
具体方法再查分析/参数/API/存储文档；实际分支、服务和任务须重新核对。
计划获接受不表示新功能已经实现或验收通过，实验参数、真实验证和发布仍遵循当前会话授权。

分析功能扩展统一从[分析功能接入指南](development.md#分析功能接入指南)开始，按参数、展示或完整能力选择接入层与检查。

个人 AI 助手：[网页操作](workflow.md#ai-分析助手) → [服务器配置](installation.md#个人-ai-配置) → [开发边界](development.md#ai-助手边界)。
