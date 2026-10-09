# scMM

`scMM` 是用于处理和分析 CyESI 单细胞质谱数据的 Python 包。它可以从
Thermo profile RAW、mzML/mzXML 原始谱构建“细胞 × m/z 特征”矩阵，并完成细胞事件识别、谱峰对齐、
归一化、缺失值填补、去同位素、精确质量注释、降维聚类、时间轨迹和代谢趋势分析。

## 功能入口

包版本为 `0.2.0`（Alpha）；本页概括使用入口，具体进展、回归和部署证据见 [CHANGELOG](CHANGELOG.md)。

| 能力 | 使用说明 |
|---|---|
| 六步项目网页、多样本信息、参数预检、提取审核及主动保存重载 | [当前网页指南](docs/workflow.md) |
| 持久批处理、共同/独立特征、失败继续、停止后续样本和重试 | [多样本流程](docs/workflow.md) |
| Thermo profile RAW 直接读取，接入 Python、CLI、目录处理及网页 | [RAW 依赖与真实样本验收](docs/thermo-raw.md) |
| H5AD、预处理起点恢复、结果失效管理、只读报告与图表重载 | [数据与输出](docs/data-output.md) |
| 统一降维、差异/Marker/相关网络、监督模型诊断和 SHAP | [分析说明](docs/analysis.md) |

待验收、工程改进和暂缓决策统一见 [roadmap](docs/roadmap.md)。

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
网页操作见 [六步流程](docs/workflow.md#网页六步项目流程)。
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
- 网页 UI：Panel、Plotly、UMAP；执行完整同步时已包含，也可单独使用
  `uv sync --locked --extra ui`。

正式分析前应使用标准样品和实验质控数据验证
参考离子、ppm 容差、SNR 阈值及归一化方案。
