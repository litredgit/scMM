# scMM 文档

按“开始使用 → 查参考 → 维护”组织，共 10 篇主题文档。项目功能摘要见[首页](../README.md)，
变化与验收记录见[CHANGELOG](../CHANGELOG.md)。

## 开始使用

1. [安装与部署](installation.md)：uv 环境、RAW 外部依赖、网页启动和服务更新。
2. [工作流程](workflow.md)：网页六步项目与 Notebook，从输入到审核、分析和保存。
3. [排错与调参](troubleshooting.md)：输入、检测、分析、任务、服务和内存问题。

## 按需查阅

| 文档 | 内容 |
|---|---|
| [参数参考](parameters.md) | 默认值、单位、算法区别、CLI 和网页 JSON 配置 |
| [Python API 与批处理](python-api.md) | 文件/目录处理、变换、注释、合并、保存和 CLI |
| [分析](analysis.md) | 统计解释、监督诊断、降维聚类、时间轨迹和绘图 |
| [数据与输出](data-output.md) | 数据模型、标准目录、H5AD、项目快照和可重复性 |
| [Thermo RAW 技术说明](thermo-raw.md) | helper 部署、二进制协议、精度差异及真实样本报告 |

## 维护

- [代理工作指南](../AGENTS.md)：当前进展、关键约定、代码导航及提问/提交规则。
- [开发指南](development.md)：模块职责、测试与发布、上游快照和历史文档追溯。
- [待办与验收边界](roadmap.md)：优先验收、工程改进、暂缓方法及长期约束。

当前网页是六步项目工作台，项目默认保存于 `/home/crs/data/results`（可用 `--project-root` 指定独立目录）；CLI/API 输出由调用参数决定。
RAW 仅支持 Thermo profile，读取保留 float64。详细旧阶段日志保存在 Git 历史，当前文档只描述最终行为。
