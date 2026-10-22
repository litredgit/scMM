# scMM

`scMM` 是用于处理和分析 CyESI 单细胞质谱数据的 Python 包。它可以从
Thermo profile RAW、mzML/mzXML 原始谱构建“细胞 × m/z 特征”矩阵，并完成细胞事件识别、谱峰对齐、
归一化、缺失值填补、去同位素、精确质量注释、降维聚类、时间轨迹和代谢趋势分析。

## 功能入口

包版本为 `0.2.0`（Alpha）；本页概括使用入口，具体进展、回归和部署证据见 [CHANGELOG](CHANGELOG.md)。

| 能力 | 使用说明 |
|---|---|
| Vue/FastAPI 六步网页：原始谱、提取审核、预处理、分析、图表与结果保存 | [Vue 网页操作](docs/workflow.md#vue-网页项目与样本) |
| 个人 API、流式只读 AI 分析助手及匿名上下文 | [AI 分析助手](docs/workflow.md#ai-分析助手) |
| 管理员只读监控、24 小时资源趋势与活动页面更新检查 | [管理员监控](docs/workflow.md#管理员监控) |
| 快照/缓存保留建议、配对归档恢复与默认关闭的管理员持续保留规则 | [持续自动保留](docs/data-output.md#持续自动保留) |
| 管理员创建账号、会话认证和单团队共享项目 | [服务器初始化与登录](docs/installation.md#服务器初始化与账号) |
| 持久批处理、共同/独立特征、失败继续、停止后续样本和重试 | [多样本流程](docs/workflow.md) |
| Thermo profile RAW 直接读取，接入 Python、CLI、目录处理及网页 | [RAW 依赖与真实样本验收](docs/thermo-raw.md) |
| H5AD、预处理起点恢复、结果失效管理、只读报告与图表重载 | [数据与输出](docs/data-output.md) |
| 统一降维、双特征散点/特征距离嵌入、差异/Marker/相关网络、监督模型诊断和 SHAP | [分析说明](docs/analysis.md) |
| 网页 Palantir 稳定 ID 根点、滑动窗口轨迹/代谢速度/代谢物趋势、命名结果和完整导出 | [伪时间与轨迹](docs/analysis.md#palantir-伪时间) |
| 独立 TIC/EIC 信号重构、残差与噪声对照，不改提取算法 | [原始信号诊断](docs/analysis.md#独立原始信号诊断) |
| 热图组别／样本筛选与排序、Nature／Cell 图形及 MetaboAnalyst 矩阵 CSV 导出 | [图形操作](docs/workflow.md#论文图细胞联动与热图) · [矩阵格式](docs/data-output.md#面向-metaboanalyst-的矩阵下载) |
| 当前数据 QC PDF、当前分析报告及完整参数/数值附件 ZIP | [报告说明](docs/analysis.md#统计解释与网页分析) |
| 网页 LMSD 候选、相关性辅助排序、天然同位素标记、分类饼图及特征/分子网络 | [注释与同位素](docs/workflow.md#注释与同位素) |

待验收、工程改进和暂缓决策统一见 [roadmap](docs/roadmap.md)。
网页覆盖范围与全部 Python 能力不同：网页注释与同位素功能保留全部峰和候选，只在显示/导出时筛选；
Python 原有删峰/求和去同位素接口与部分时间/趋势分析继续保留，边界见[分析说明](docs/analysis.md)。
待验收与新会话起点见 [发展计划](docs/roadmap.md#新会话起点)。

同行复核提取方法可直接阅读[细胞事件与特征峰确认流程](docs/cell-feature-identification.md)。

## 从这里开始

- 代理接手与协作规则：[AGENTS.md](AGENTS.md)。
- [安装与部署](docs/installation.md) → [网页与 Notebook 工作流程](docs/workflow.md)
- [参数参考](docs/parameters.md) · [Python/CLI](docs/python-api.md) · [分析](docs/analysis.md)
- [排错](docs/troubleshooting.md) · [待办](docs/roadmap.md) · [完整文档索引](docs/README.md)

## 最短使用路径

创建环境并安装项目：

```bash
uv sync --locked --all-extras --dev
```

该命令根据 `pyproject.toml` 和已提交的 `uv.lock` 创建项目专用 `.venv`，并以可编辑模式安装
scMM。后续命令统一通过 `uv run` 执行，无需手工激活环境。

本机生产网页使用 main / 5006，开发使用 dev / 5007，Python 环境及结果分别隔离；
启动、发布与回滚见 [安装部署](docs/installation.md#开发与生产分离)。
网页启动前必须完成仓库外资源配置和管理员初始化，不支持匿名启动；普通成员不能配置服务器路径。
网页操作见 [Vue 六步流程](docs/workflow.md#vue-网页项目与样本)。
自动化处理可直接使用命令行（参考离子必须按实验修改）：

```bash
uv run --locked scmm-process input.mzML results --ref-mz 734.5929
uv run --locked scmm-process raw-data/ results --ref-mz 734.5929 --jobs 4
```

Python 调用、保存重载和目录处理见 [API 与批处理](docs/python-api.md)。
需要逐步质控和绘图时打开 [scMM_workflow.ipynb](scMM_workflow.ipynb)，
修改顶部参数单元后按 [Notebook 流程](docs/workflow.md#notebook参数化流程) 执行。

## 支持范围

- Python：3.11–3.12；`.python-version` 将本地开发默认固定为 Python 3.12。
- 原始谱：mzML、mzXML；Thermo RAW 仅接受 profile，需另行部署 .NET 8 reader，
  `uv sync` 不安装厂商组件，详见[安装说明](docs/installation.md#thermo-raw-额外依赖)。
- 核心依赖：PyOpenMS、NumPy、pandas、SciPy、scikit-learn、AnnData。
- 可选分析：Matplotlib、Seaborn、UMAP、Palantir、Leiden/Louvain。
- Vue 网页：Vue 3、TypeScript、FastAPI；Python 使用 `web` extra，前端需 Node.js 构建，
  运行入口为 `scmm-web`。完整六步功能与构建步骤见[安装部署](docs/installation.md#vuefastapi-网页)。

正式分析前应使用标准样品和实验质控数据验证
参考离子、ppm 容差、SNR 阈值及归一化方案。

网页新增独立降维/聚类/注释板块、PCA 二/三维选择、分类权重 Marker、完整 SHAP 解释和热图，支持点击细胞比较质谱。
图形提供论文尺寸、SVG/PDF/指定 DPI PNG 与完整作图数据导出；管理员维护支持会话暂存及模型恢复。操作见[网页流程](docs/workflow.md)。
