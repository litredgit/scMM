# scMM 文档

本页只提供阅读路径和文档入口。项目概览见 [首页](../README.md)，
具体进展和历史验收见 [CHANGELOG](../CHANGELOG.md)，任务结束时的文档更新规则见
[AGENTS.md](../AGENTS.md#任务结束时的文档更新规则)。

当前使用行为、待办和历史证据分别维护；主题文档不重复维护阶段状态或测试数量。

## 开始使用

1. [安装与部署](installation.md)：uv 环境、RAW 外部依赖、网页启动和服务更新。
2. [工作流程](workflow.md)：网页六步项目与 Notebook，从输入到审核、分析和保存。
3. 运行失败时查 [排错与调参](troubleshooting.md)，需要选择或解释参数时查 [参数参考](parameters.md)。

## 按需查阅

| 文档 | 内容 |
|---|---|
| [参数参考](parameters.md) | Notebook/API/CLI/网页默认值的区别、单位、算法阈值和 JSON 配置 |
| [Python API 与批处理](python-api.md) | 提取、变换、注释、合并、保存重载与 CLI 调用示例 |
| [分析](analysis.md) | 分析方法、不同分析入口、统计解释、轨迹与绘图、暂缓方法定义 |
| [数据与输出](data-output.md) | 数据模型、目录/文件格式、AnnData/H5AD 映射、项目快照和归档 |
| [Thermo RAW 技术说明](thermo-raw.md) | reader 依赖与构建、流协议、精度边界、原始对照报告和复现 |

## 维护

- [代理工作指南](../AGENTS.md)：主要设计、模块职责及提问/提交规则；具体进展见 CHANGELOG。
- [开发指南](development.md)：模块职责、测试与发布、main/dev 环境分工、上游快照和历史文档追溯。
- [待办与验收边界](roadmap.md)：剩余验证与发布核对、按模块整理的工程改进、可选功能及暂缓恢复条件；已通过验收的工作归 CHANGELOG。
- [CHANGELOG](../CHANGELOG.md)：实现、验证、验收和部署记录，包括历史环境证据。
