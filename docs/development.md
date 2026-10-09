# 开发与质量检查

[返回文档索引](README.md) · [安装说明](installation.md)

本页负责模块分工、扩展方式、兼容性回归、检查与发布流程。主要设计和协作规则见
[AGENTS.md](../AGENTS.md)，环境安装见安装说明；实现进展不在本页维护。

## 代码结构

当前入口为 `ui/app.py` 的项目工作台；`ui/project_views.py` 管理项目原始谱展示，
`ui/layout.py` 管理响应式布局及未保存离页提示。项目持久化与批次编排分别在
`application/projects.py` 和 `application/project_batch.py`，RAW 流读取在 `file/readers/`。
下列树保留其他模块职责，使用流程以 [当前网页指南](workflow.md) 为准。

```text
scMM/
├── cli.py                 # scmm-process 命令行入口
├── application/
│   ├── projects.py        # 项目清单、快照、修订冲突和保存重载
│   ├── project_batch.py   # 多样本持久 worker、重试及审核合并
│   ├── workbench.py       # 数据身份、预处理、分析与结果生命周期
│   ├── preview_cache.py   # 完整预览/共同特征的身份校验与复用
│   ├── preferences.py     # 全局预设、显式保存与 CPU 默认值
│   ├── parameters.py      # 参数定义、帮助与 JSON 默认值
│   ├── storage.py         # 挂载目录白名单、路径解析和越界防护
│   ├── raw_preview.py     # TIC、EIC、合并谱和原始文件摘要
│   ├── processing.py      # 处理参数、输入/输出边界和预检计划
│   ├── tasks.py           # 单任务锁、原子状态、日志和进程管理
│   ├── worker.py          # 独立处理进程、运行清单和质量产物编排
│   └── quality.py         # 质量统计、PCA/UMAP 及持久化文件
├── ui/
│   ├── cli.py             # scmm-ui 服务启动入口
│   ├── app.py             # 项目首页及六步工作流
│   ├── project_views.py   # 项目原始谱展示与预览编排
│   ├── raw_components.py  # 可复用的原始谱及分析控件
│   ├── file_browser.py    # 根目录内的浏览、搜索与跨目录选择
│   ├── presentation.py    # 表格、图形与数值显示
│   ├── analysis_plots.py  # 分析结果图形
│   ├── layout.py          # 任务栏、图表比例和离页提醒
│   ├── workbench.py       # 分析页面控件
│   └── processing.py      # 旧处理面板及共享处理控件
├── file/
│   ├── io.py              # 原始文件分发、XML 完整性与稳定导出
│   ├── readers/           # Thermo RAW 二进制流、可重开 source 与生命周期
│   ├── _spectrum.py       # Orbitrap 网格、谱汇总与峰细化
│   ├── _alignment.py      # 峰到目标 m/z 的匹配与帧聚合
│   ├── data.py            # CyESIData 稳定门面与构造入口
│   ├── _dataset_loading.py # 已处理/原始数据装载与组合
│   ├── _dataset_processing.py # 预处理、变换与数据集合并
│   ├── _dataset_interop.py # 保存、访问、注释与 AnnData 转换
│   ├── _deisotope.py      # 去同位素的纯计算、分配与元数据构建
│   └── batch.py           # 独立批处理与结果合并
├── analysis/              # QC、统计、统一降维、监督模型与诊断
├── util/
│   ├── peak.py            # 局部谱统计与细胞事件窗口归约
│   ├── normalize.py       # 归一化注册表和内置方法
│   ├── annotation.py      # SDF 读取与稳定搜索门面
│   ├── _adducts.py        # 加合物定义与质量换算
│   ├── _annotation_search.py # 候选生成、排序与结果模式
│   └── denoise.py         # 矩阵分解与峰重建工具
└── plot/
    ├── engine.py          # PlotEngine 共享状态与领域能力组合
    ├── _engine_*.py       # 降维、轨迹、聚类和特征网络领域能力
    ├── _trajectory.py     # Palantir、窗口轨迹、速度和趋势统计
    ├── _trend_clustering.py # 趋势距离与聚类算法
    ├── embedding.py       # 轻量降维接口
    └── msplot.py          # EIC、谱和调试图
```

`tools/thermo_raw_reader/` 保存 C# helper 与 NuGet 锁文件；`tools/validate_thermo_*.py`
用于真实 RAW 对照，报告位于 `docs/validation/`。厂商组件不随 Python 包安装。

测试位于 `tests/`，覆盖数据保存/加载、对齐、去同位素、归一化、谱 I/O、输入/输出路径边界、
原始谱预览、后台任务、项目保存/重载、多样本审核、RAW 协议/流式处理、质量产物、网页控件、绘图、轨迹和 CLI。

## 开发环境

日常修改在 `dev` worktree，`main` worktree 专用于生产；目录、服务与发布/回滚命令见
[开发与生产分离](installation.md#开发与生产分离)。5007 用于开发检验，5006 用于正式实验。

```bash
uv sync --locked --all-extras --dev
```

修改依赖时使用 `uv add`/`uv remove`，或编辑 `pyproject.toml` 后重新锁定：

```bash
uv lock
uv sync --locked --all-extras --dev
```

依赖升级应单独执行 `uv lock --upgrade`，避免普通环境同步意外改变已验证版本。

## 完整验证

从仓库根目录运行：

```bash
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked python -m pytest -W error
uv build --no-sources
```

`pytest -W error` 会把警告提升为错误，有助于尽早发现 pandas、NumPy、scikit-learn 或 PyOpenMS
升级引入的兼容问题。
从仓库根目录使用 `python -m pytest`，确保本地 `scripts` 快照工具也位于导入路径；
部分环境中直接运行 pytest 入口脚本会在收集快照测试时找不到该模块。

只运行相关测试：

```bash
uv run --locked python -m pytest tests/test_data.py -q
uv run --locked python -m pytest tests/test_io.py -q
uv run --locked python -m pytest tests/test_trajectory.py -q
```

覆盖率：

```bash
uv run --locked python -m pytest --cov=scMM --cov-report=term-missing
```

文档修改可单独运行以下检查，验证本地链接、Python 示例和 Notebook 基本约定：

```bash
uv run --locked python -m pytest tests/test_documentation.py -q
```

CI 对 dev/main/refined 的 push 和 pull request 执行 Python 3.11/3.12 矩阵。
本机通过与远端 CI 通过应分别记录，不以配置存在代替实际验收。

## Notebook 检查

通用 notebook 应满足：

- 所有用户路径和实验参数集中在参数单元。
- 不包含个人主目录绝对路径。
- 提交前清除大量执行输出和临时图。
- 参数单元带 `parameters` 标签，便于 Papermill 等工具注入配置。
- 示例默认值不执行不可逆或高风险步骤。
- 文档中说明无法仅凭示例默认值确定的实验参数，尤其是 `REF_MZ`。

基本结构和语法检查可以在没有科学计算依赖时完成：

```bash
uv run --locked python -m json.tool scMM_workflow.ipynb >/dev/null
uv run --locked python - <<'PY'
import ast
import json

with open("scMM_workflow.ipynb", encoding="utf-8") as handle:
    notebook = json.load(handle)

for number, cell in enumerate(notebook["cells"]):
    if cell["cell_type"] == "code":
        ast.parse("".join(cell["source"]), filename=f"cell-{number}")
print("notebook syntax OK")
PY
```

这不能代替在 uv 管理的项目环境中使用代表性 mzML 执行整个流程。

## API 设计约定

- 高层可变换方法通常原地修改 `CyESIData` 并返回自身，以支持方法链。
- 保存方法返回实际创建的路径。
- 公开入口应验证维度、范围和有限数值，并给出明确异常。
- `data`、`peak_meta` 和 `feature_meta` 必须保持行列一一对应。
- 随机算法公开 `random_state`/`seed`。
- 仅由单个功能需要的可选依赖（如 Palantir、UMAP、Seaborn、Leiden/Louvain）应在调用对应
  功能时才导入，并在缺失时给出针对性提示。
- `CyESIData` 只负责容器状态和处理溯源；较长的数值流程应拆到相邻的私有模块，并优先实现为
  不修改输入的纯函数。`_deisotope.py` 是这一边界的参考：公开方法组装参数并提交结果，候选检测、
  回归、筛选、分配和元数据生成各自独立。
- 数据容器的新能力应归入装载、处理或互操作领域之一；`data.py` 只组合这些能力并维护稳定的
  构造入口。跨数据集合并应先生成完整 `DatasetState`，确认成功后再一次性更新当前对象。
- 峰处理流程应把局部统计、事件分段和结果组装分开；并行执行的单事件函数应保持为模块级纯函数，
  便于独立验证且避免闭包携带整个调用上下文。
- 绘图入口只负责编排；输入整理、类别解析、坐标轴配置和标注选择应拆成可单独测试的模块级辅助
  函数。不得通过 `pop()` 等操作修改调用方传入的参数字典。
- 网页控件不得直接读取任意客户端路径。所有选择必须经过 `StorageCatalog` 的配置根目录和真实路径
  双重校验；TIC/EIC 等领域计算保留在 `application/`，Panel 回调只管理会话状态和展示。
- 旧任务输出通过 `OutputCatalog` 限制目录；当前项目通过 `ProjectStore` 固定根目录及产物路径校验，
  保存时先写快照、后发布清单，并检查修订冲突。批量提取必须在独立 worker 中执行，
  使用持久状态恢复；预览和分析当前仍同步执行，后台化见[待办清单](roadmap.md)。

## 兼容性回归边界

以下编号用于相关修改及上游移植的回归审阅，不表示未完成缺陷：

- **REG-01**：保留 group_key holdout/CV、SMOTE 最小样本及非有限输入检查，失败必须报错。
- **REG-02**：保留旧目录兼容、H5AD raw/层/嵌入保真、原子发布和默认防覆盖，不整体替换数据容器。
- **REG-03**：保留 XML 完整性、RAW 超时/协议/资源回收、归一化零值、SDF、reference ppm 与 SNR 定义；直接 reader 失败不隐式转换。
- **REG-04**：保留 frame_id/ms_level/native_id 已验证的元数据路径。
- **REG-05**：保留持久任务、审核合并、主动保存及存储目录边界。
- **VAL-04**：holdout PR/AP、校准和 Brier 不可在反复调参后继续解释为独立测试；细胞数不等于生物重复数。

## 添加归一化方法

归一化方法通过注册表扩展：

```python
from scMM.util.normalize import register_norm


@register_norm("custom")
def norm_custom(X, params):
    scale = params.get("scale", 1.0)
    return X * scale
```

新方法应验证二维输入、零分母、NaN/Inf 和参数类型，并在 `tests/test_normalize.py` 添加测试。

## 添加降维方法

轻量接口使用 `register_dim`：

```python
from scMM.plot.embedding import register_dim


@register_dim("custom")
def run_custom(X, params):
    model = CustomModel(**params)
    return model.fit_transform(X)
```

输出必须是每个细胞一行、至少两列的二维数组。

## 数据与 Git

- 不提交原始 mzML/mzXML、处理矩阵、H5AD 或大体积执行输出，除非仓库策略明确允许。
- 测试数据应尽量使用代码构造的小型合成谱和矩阵。
- 不在 notebook 或源码中写个人绝对路径。
- 提交信息建议使用项目现有风格，例如 `docs: ...`、`refactor: ...`、`test: ...`。
- 提交前查看 `git status` 和 `git diff --check`，避免把无关本地修改带入提交。

## 发布前检查

先同步锁定环境并完成 [完整验证](#完整验证)，再用本次构建的 wheel 检查独立安装入口。
核对 dist 中选中的文件确为本次产物：

```bash
uv run --isolated --no-project \
  --with "$(find dist -maxdepth 1 -name '*.whl' -print -quit)" \
  scmm-process --help
```

还应在受支持的 Python 版本和至少一个代表性 mzML/mzXML 文件上完成端到端验证。

## 上游源码快照

外部交付单独保存在 `.upstream-snapshots.git/` 裸仓库的 `snapshots` 分支及 `snapshot/<名称>` 标签，
主仓库 `vendor/snapshots` 同步对象。交付提交只代表接收顺序，不伪造作者开发历史。
已收录 `scMM-new`（`bdce317`，2026-09-21）和 `SCMM-GUI-0.2.0-source`（`f961809`，2026-09-22）。

从仓库根目录导入，重复使用目录时指定新名称：

```sh
uv run --locked python scripts/import_upstream_snapshot.py 新交付目录 --name 新版本名称 --received-date YYYY-MM-DD
git log --oneline vendor/snapshots
git diff dev vendor/snapshots -- scMM/
git --git-dir=.upstream-snapshots.git show snapshots:.snapshot.json
```

脚本保留交付源码、PDF、配置及可执行位，跳过 Git/缓存目录，拒绝软链接；`.snapshot.json`
记录来源、排除项与 SHA-256。同名同内容不重复导入，同名异内容拒绝；新交付删除的文件仍可从旧标签找回。
只含包源码的交付统一映射到 `scMM/`，完整项目保留布局。原目录不自动随修改更新快照。
脚本不执行交付代码、不切换当前分支或改暂存区，但需要 Git 对象/引用与 `.git/info/exclude` 写权限。
按功能审阅移植，不直接整体合并快照分支。

快照标签留在本地裸仓库，普通推送 dev 不会备份它们。使用新的文件名导出并另存到其他磁盘：

```sh
git --git-dir=.upstream-snapshots.git bundle create /tmp/scmm-upstream-备份日期.bundle --all
git clone --bare /tmp/scmm-upstream-备份日期.bundle /tmp/scmm-upstream-restored.git
```

## 文档维护与历史追溯

文档职责及任务结束后的更新选择以 [AGENTS.md](../AGENTS.md#文档职责与更新时机) 为准，
不在本页重复维护另一套规则。文档变动后检查本地链接/锚点、Python 示例和 Notebook 基本约定；
检查结果记到 CHANGELOG，原始机器报告留在 `docs/validation/`。

旧编号教程、实施日志和暂停续接信息不再作为活跃文档；需要详细历史时从 Git 查看。
原 17 篇编号文档整理前基线为 `bc3e35d`，例如：

```sh
git show bc3e35d:docs/10-functional-port.md
git show bc3e35d:docs/15-project-redesign.md
git show bc3e35d:docs/16-thermo-raw.md
```
