# scMM

`scMM` 是用于处理和分析 CyESI 单细胞质谱数据的 Python 包。它可以从
Thermo profile RAW、mzML/mzXML 原始谱构建“细胞 × m/z 特征”矩阵，并完成细胞事件识别、谱峰对齐、
归一化、缺失值填补、去同位素、精确质量注释、降维聚类、时间轨迹和代谢趋势分析。

## 当前能力与状态

截至 2026-10-08，按仓库代码及已记录验收整理；包版本仍为 `0.2.0`（Alpha）。

| 已完成能力 | 使用说明与证据 |
|---|---|
| 六步项目网页、多样本信息、参数预检、提取审核及主动保存重载 | [当前网页指南](docs/workflow.md) |
| 持久批处理、共同/独立特征、失败继续、停止后续样本和重试 | [多样本流程](docs/workflow.md) |
| Thermo profile RAW 直接读取，接入 Python、CLI、目录处理及网页 | [RAW 依赖与真实样本验收](docs/thermo-raw.md) |
| H5AD、预处理起点恢复、结果失效管理、只读报告与图表重载 | [数据与输出](docs/data-output.md) |
| 统一降维、差异/Marker/相关网络、监督模型诊断和 SHAP | [分析说明](docs/analysis.md) |
| 常驻任务栏、多 EIC 单遍计算、未保存离页提醒、中文后台任务修复 | [网页指南](docs/workflow.md)、[变更记录](CHANGELOG.md) |

最近记录的完整回归为 2026-10-05 的 **305 项通过**；同日功能已部署至主仓库 5006 服务，
浏览器首页验收通过。这是历史验收记录，不代表本次重新检查在线服务或远端 CI。
尚待真实多样本验收、性能/资源管理等工作统一见[待办清单](docs/roadmap.md)。

## 从这里开始

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

打开 [scMM_workflow.ipynb](scMM_workflow.ipynb)，至少修改：

```python
INPUT_PATH = Path("data/sample.mzML")
OUTPUT_ROOT = Path("results")
REF_MZ = 734.5929  # 必须换成实验使用的参考离子
```

然后执行 `Run All`。Notebook 可以自动识别单个原始文件、原始文件目录和已有处理结果目录。

也可以直接使用命令行：

```bash
uv run --locked scmm-process input.mzML results --ref-mz 734.5929
uv run --locked scmm-process raw-data/ results --ref-mz 734.5929 --jobs 4
```

或使用 Python API：

```python
from scMM.file.data import CyESIData

data = CyESIData.load_from_file(
    "sample.mzML",
    ref_mz=734.5929,
    cell_snr=5.0,
    peak_snr=3.0,
)
data.normalize("total")
result_dir = data.save("results")
```

重新载入时必须传入实际的数据集目录，而不是它的父目录：

```python
reloaded = CyESIData.load_from_processed(result_dir)
```

在本机启动引导式网页，用服务器已经挂载的目录直接选择、预览并处理原始数据：

```bash
uv run --locked scmm-ui \
  --storage "原始数据=/mnt/ms-data" \
  --output "处理结果=/mnt/scmm-results" \
  --address 0.0.0.0 \
  --port 5006
```

页面按“样本 → 原始谱与参数 → 提取审核 → 预处理 → 分析 → 结果与保存”组织。
项目根目录固定为 `/home/crs/data/results`，启动前须存在且可写；`--output` 保留兼容，
不改变项目根目录。原始文件仅引用，不复制。后台提取结束后须审核并纳入成功样本，
再主动点击“保存项目”；刷新不会自动保存编辑。预览与分析仍同步执行。
具体操作见[当前网页指南](docs/workflow.md)，网络和挂载配置参考
[部署说明](docs/installation.md)中的相关章节。

## 支持范围

- Python：3.11–3.12；`.python-version` 将本地开发默认固定为 Python 3.12。
- 原始谱：mzML、mzXML；Thermo RAW 仅接受 profile，需另行部署 .NET 8 reader，
  `uv sync` 不安装厂商组件，详见[安装说明](docs/installation.md#thermo-raw-额外依赖)。
- 核心依赖：PyOpenMS、NumPy、pandas、SciPy、scikit-learn、AnnData。
- 可选分析：Matplotlib、Seaborn、UMAP、Palantir、Leiden/Louvain。
- 网页 UI：Panel、Plotly、UMAP；执行完整同步时已包含，也可单独使用
  `uv sync --locked --extra ui`。

项目当前版本为 `0.2.0`，开发状态为 Alpha。正式分析前应使用标准样品和实验质控数据验证
参考离子、ppm 容差、SNR 阈值及归一化方案。
