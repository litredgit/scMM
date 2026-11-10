# scMM

`scMM` 是用于处理和分析 CyESI 单细胞质谱数据的 Python 包。它可以从
Thermo profile RAW、mzML/mzXML 原始谱构建“细胞 × m/z 特征”矩阵，并完成细胞事件识别、谱峰对齐、
归一化、缺失值填补、去同位素、精确质量注释、降维聚类、时间轨迹和代谢趋势分析。

## 功能入口

当前版本为 0.2.0（Alpha）。

| 场景 | 文档 |
|---|---|
| 网页：提取审核、预处理、分析与项目保存 | [网页操作](docs/02-workflow.md) |
| 脚本、Notebook 与命令行 | [Python/CLI](docs/05-python-api.md) · [Notebook](docs/02-workflow.md#notebook参数化流程) |
| 质谱提取与候选注释 | [细胞与特征识别](docs/03-cell-feature-identification.md) · [离子归组](docs/02-workflow.md#离子归组与化合物证据) |
| 统计、降维、监督模型与时间趋势 | [分析](docs/07-analysis.md) · [时间与趋势](docs/08-time-analysis.md) |
| 查看文件、图表和矩阵导出格式 | [数据与输出](docs/06-data-output.md) |

## 从这里开始

- [安装与部署](docs/01-installation.md) → [网页与 Notebook 工作流程](docs/02-workflow.md)
- [参数参考](docs/04-parameters.md) · [Python/CLI](docs/05-python-api.md) · [分析](docs/07-analysis.md)
- [排错](docs/11-troubleshooting.md) · [待办](docs/14-roadmap.md) · [完整文档索引](docs/README.md)

## 最短使用路径

创建环境并安装项目：

```bash
uv sync --locked --all-extras --dev
```

该命令根据 `pyproject.toml` 和已提交的 `uv.lock` 创建项目专用 `.venv`，并以可编辑模式安装
scMM。后续命令统一通过 `uv run` 执行，无需手工激活环境。

本机生产网页使用 main / 5006，开发使用 dev / 5007，Python 环境及结果分别隔离；
启动、发布与回滚见 [安装部署](docs/01-installation.md#开发与生产分离)。
网页启动前必须完成仓库外资源配置和管理员初始化，不支持匿名启动；普通成员不能配置服务器路径。
网页操作见 [Vue 六步流程](docs/02-workflow.md#vue-网页项目与样本)。
自动化处理可直接使用命令行（参考离子必须按实验修改）：

```bash
uv run --locked scmm-process input.mzML results --ref-mz 734.5929
uv run --locked scmm-process raw-data/ results --ref-mz 734.5929 --jobs 4
```

Python 调用、保存重载和目录处理见 [API 与批处理](docs/05-python-api.md)。
需要逐步质控和绘图时打开 [scMM_workflow.ipynb](scMM_workflow.ipynb)，
修改顶部参数单元后按 [Notebook 流程](docs/02-workflow.md#notebook参数化流程) 执行。

## 支持范围

- Python：3.11–3.12；`.python-version` 将本地开发默认固定为 Python 3.12。
- 原始谱：mzML、mzXML；Thermo RAW 仅接受 profile，需另行部署 .NET 8 reader，
  `uv sync` 不安装厂商组件，详见[安装说明](docs/01-installation.md#thermo-raw-额外依赖)。
- 核心依赖：PyOpenMS、NumPy、pandas、SciPy、scikit-learn、AnnData。
- 可选分析：Matplotlib、Seaborn、UMAP、Palantir、Leiden/Louvain。
- Vue 网页：Vue 3、TypeScript、FastAPI；Python 使用 `web` extra，前端需 Node.js 构建，
  运行入口为 `scmm-web`。完整六步功能与构建步骤见[安装部署](docs/01-installation.md#vuefastapi-网页)。

正式分析前应使用标准样品和实验质控数据验证
参考离子、ppm 容差、SNR 阈值及归一化方案。
