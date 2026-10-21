# 开发与质量检查

[返回文档索引](README.md) · [安装说明](installation.md)

本页负责模块分工、扩展方式、兼容性回归、检查与发布流程。主要设计和协作规则见
[AGENTS.md](../AGENTS.md)，环境安装见安装说明；实现进展不在本页维护。
2026-10-18 的改进依据与实施建议见[审阅交接](improvement-review.md)，任务当前状态见
[roadmap](roadmap.md#审阅新增改进)；建议中的模块拆分不代表本页所述现有结构已经改变。

## 代码结构

Vue/FastAPI 网页按功能组织完整六步交互；前端页面在仓库根 `frontend/src/features/`，
共享组件、路由、请求客户端及 Pinia 状态分别在相邻 `components/`、`router/`、`api/`、`stores/`。
`scMM/api/routers/` 按项目、样本、存储、原始谱、提取、分析、结果和预设拆分 HTTP 边界，
`schemas.py`、`workflow_schemas.py` 定义接口契约并校验科学参数。
`application/web_workspace.py` 保持工作区门面，负责注册/过期、所有者复核、访问锁、写入修订与事务门禁；不依赖前端或 FastAPI。
`workspace_state.py` 定义工作区状态与错误，`web_projects.py` 负责项目/样本操作、候选复制和元数据映射，
`web_ai.py` 发布已筛选摘要并在短锁下读取。旧门面导出保持兼容；项目/样本操作仍经过同一 mutate/access 门禁，
AI 网络调用继续不占科学工作区锁。
`web_raw.py`、`web_analysis.py`、`web_results.py` 分别编排原始谱/任务、分析及下载/管理。
`application/result_catalog.py` 集中已有统计/监督结果的操作名、关联图、元数据依赖、只读报告序列化与重载；
前端 `features/analysis/results.contract.json` 保留显式映射，由契约测试与目录逐项核对。
`plot/presentation.py`、`plot/raw.py`、`plot/workbench.py` 提供网页使用的共享图形构建。
矩阵与模型留在 Python 应用层，前端只接收摘要和展示数据。`api/cli.py` 是唯一网页启动入口。

项目持久化与批次编排分别在 `application/projects.py` 和 `application/project_batch.py`，
RAW 流读取在 `file/readers/`。
下列树保留其他模块职责，使用流程以 [当前网页指南](workflow.md) 为准。

```text
scMM/
├── cli.py                 # scmm-process 命令行入口
├── application/
│   ├── projects.py        # 项目清单、快照、修订冲突和保存重载
│   ├── naming.py          # 北京时间与项目/批次/快照/H5AD 默认命名
│   ├── trash.py           # 删除计划、引用/任务保护及回收区恢复
│   ├── retention.py       # 只读快照/缓存保留建议、引用与任务核实；不执行清理
│   ├── project_batch.py   # 多样本持久 worker、重试及审核合并
│   ├── workbench.py       # 数据身份、预处理、分析与结果生命周期
│   ├── preview_cache.py   # 完整预览/共同特征的身份校验与复用
│   ├── cell_preview.py    # 冻结提取请求、独立预览进程与持久阶段状态
│   ├── preferences.py     # 全局预设、显式保存与 CPU 默认值
│   ├── parameters.py      # 参数定义、帮助与 JSON 默认值
│   ├── storage.py         # 挂载目录白名单、路径解析和越界防护
│   ├── raw_preview.py     # TIC、EIC、合并谱和原始文件摘要
│   ├── processing.py      # 处理参数、输入/输出边界和预检计划
│   ├── tasks.py           # 单任务锁、原子状态、日志和进程管理
│   ├── worker.py          # 独立处理进程、运行清单和质量产物编排
│   └── quality.py         # 质量统计、PCA/UMAP 及持久化文件
├── api/
│   ├── cli.py             # scmm-web 服务启动入口
│   ├── app.py             # 同源静态资源、HTTP 边界及单进程工作区
│   ├── routers/           # 按功能拆分的版本化接口
│   └── schemas.py         # 请求/响应契约与参数校验
├── file/
│   ├── io.py              # 原始文件分发、XML 完整性与稳定导出
│   ├── readers/           # Thermo RAW 二进制流、可重开 source 与生命周期
│   ├── _spectrum.py       # Orbitrap 网格、谱汇总与峰细化
│   ├── _alignment.py      # 峰到目标 m/z 的匹配与帧聚合
│   ├── data.py            # CyESIData 稳定门面与构造入口
│   ├── _dataset_loading.py # 已处理/原始数据装载与组合
│   ├── _dataset_processing.py # 预处理、变换与数据集合并
│   ├── _dataset_interop.py # 保存门面、访问、注释与 AnnData 转换
│   ├── _dataset_persistence.py # 旧目录候选写入/校验、读写锁、发布回滚与中断恢复
│   ├── _deisotope.py      # 去同位素的纯计算、分配与元数据构建
│   └── batch.py           # 独立批处理与结果合并
├── analysis/              # QC、统计、统一降维、监督模型；_validation.py 解释历史与验证边界
├── util/
│   ├── peak.py            # 局部谱统计与细胞事件窗口归约
│   ├── normalize.py       # 归一化注册表和内置方法
│   ├── intensity.py       # 共享强度来源分类、变换传播与版本化持久化
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
    └── msplot.py          # EIC 与质谱绘图
```

`tools/thermo_raw_reader/` 保存 C# helper 与 NuGet 锁文件；`tools/validate_thermo_*.py`
用于真实 RAW 对照，报告位于 `docs/validation/`。厂商组件不随 Python 包安装。

测试位于 `tests/`，覆盖数据保存/加载、对齐、去同位素、归一化、谱 I/O、输入/输出路径边界、
原始谱预览、后台任务、项目保存/重载、多样本审核、RAW 协议/流式处理、质量产物、HTTP 接口、Vue 浏览器交互、绘图、轨迹和 CLI。

## 前后端能力覆盖

以下按当前交付代码核对 Python/Notebook、应用层/HTTP 与 Vue 的覆盖范围；只列能力边界，
执行优先级、依赖及未完成验收统一在 [roadmap](roadmap.md)。规划中的接口和控件尚未实现。
路径默认相对 `scMM/`；Notebook 和 `frontend/` 相对仓库根。公共门面或图形包装函数存在，
不等于已有可直接绑定按钮的应用服务。

| 能力 | Python / Notebook 入口 | 当前应用/HTTP/Vue | 规划或保留边界 |
|---|---|---|---|
| 原始谱与提取 | `CyESIData.load_from_file()` / `load_from_directory()`、`file/readers/` | Vue 有 TIC/多 EIC/合谱/单扫描、SNR 预览、批次与人工审核 | PERF-01/TASK-01～03/VAL-05 改执行与资源，不改现有数值；legacy 仅保留 Python/CLI/旧产物兼容，不恢复 Vue 方法选择器 |
| 基础预处理/QC | `analysis/quality.py`、`analysis/preprocessing.py`、`util/normalize.py`、`file/_dataset_processing.py` | 筛选、七种归一化、四种插补、异常检测高级参数、稳定 ID 子集和层/完整起点恢复 | PARAM-01 / SUBSET-01 / QC-01 已接待统一验收；各入口默认值分别保持，失败候选不提交 |
| 天然同位素 | 原 `CyESIData.deisotope()`、`file/_deisotope.py`；网页 `util/lipid_isotopes.py` | 网页按数据库分子式/加合物计算天然分布，保留所有峰，只标记、审阅与筛选导出 | ISO-01～03 与 ANN 联合；网页不使用旧 API 的删峰/求和及平方矩阵 |
| SDF 精确质量注释 | 原 `get_annotation()`；网页 `util/lipid_annotation.py` / `lipid_rules.py` | LMSD 本地准备、质量索引、完整候选、规则/预设、人工指定、独立版本及 CSV 已接入 | ANN-01～03；保留用户验收，背景任务迁移仍归 M2；Python/Notebook 旧默认值保持 |
| 细胞降维/聚类 | `analysis/embedding.py`、`analysis/clustering.py`、`PlotEngine`、`plot/embedding.py` | 五种降维、五种聚类、聚类参数白名单及着色已有；工作台保留候选提交，领域辅助函数负责参数校验/计算 | PARAM-03 已核对现有显式降维字段均有控件；三套 Python 入口的默认值/返回值不混用，Matplotlib 包装不重复造按钮 |
| 差异/Marker/相关网络 | `analysis/statistics.py`、`plot/_engine_statistics.py` | 检验、全局 FDR、筛选/分页、图形与导出已有 | 保持 STAT-01 解释和结果生命周期；不是待重新移植的功能 |
| 监督诊断/潜变量/SHAP | `analysis/supervised.py` | 分组验证、四模型、ROC/PR/校准、潜变量及 SHAP 已有 | PARAM-03 已接入 model_parameters.py 白名单/组合/训练折校验、四模型控件及 SHAP 显示设置；不序列化可执行模型 |
| Palantir 与窗口轨迹 | `PlotEngine.run_palantir()` / `compute_trajectory()` | 无应用/HTTP/Vue 分析入口 | TIME-01；现有 Python 方法和暂缓的上游启发式方法分别管理 |
| 代谢速度 | `PlotEngine.metabolic_velocity()` | 无对应入口 | TIME-02，沿现有参数化坐标的窗口变化速度，不能解释为示踪通量 |
| 代谢物趋势/趋势聚类 | `plot_metabolite_trends()` / `plot_trend_clusters()` | 无对应入口 | TIME-03/04，输入时间、窗口、统计量和趋势距离可追溯 |
| 特征距离嵌入 | `PlotEngine.feature_network()`；网页 `analysis/feature_embedding.py` | 独立特征距离 UMAP、层/ID/名称/类别、完整表及只读重载 | PLOT-02 待统一验收；Pearson 绝对相关/Euclidean 与相关阈值网络区分，常量/缺失及资源门限有明确规则 |
| 双特征散点/回归 | `PlotEngine.plot_feature_scatter()`；网页 `analysis/feature_scatter.py` | 独立面板、精确 ID/层/着色、全体细胞回归、完整导出及只读图重载 | PLOT-01 待用户统一验收；网页不采用 Notebook 的最近质量匹配，不将细胞级回归解释为生物重复验证 |
| 已处理结果合并 | `CyESIData.alignwith()`、`file.batch.concat()` | 当前已有原始样本提取审核合并；导入独立结果会替换当前数据 | MERGE-01；concat 当前读取旧结果目录，不是任意 H5AD 合并服务，须适配来源/特征/起点 |
| 显式数据子集 | `AnalysisWorkspace.subset()` | 稳定细胞/特征 ID、数量预览、手动应用和完整起点恢复 | SUBSET-01 待统一验收；不是 `CyESIData.__getitem__` 的最近 m/z 强度读取，失败原子性及保存重开受检查 |
| 采集稳定性 QC | Notebook 稳定性段；网页 `analysis/stability.py` | 显式坐标/来源/参考特征、箱图/窗口数量/来源中位谱相关和完整表、只读图重载 | QC-01 待统一验收；存储顺序不当采集时间，不把细胞级 QC 当生物重复验证 |
| QC / 当前分析报告 | Python `analysis.quality.render_quality_report()`；网页 `analysis/quality_pdf.py`、`application/reporting.py` | 当前矩阵 QC PDF、分页分析摘要及完整数值/参数/图形附件 ZIP | REPORT-01 待统一验收；请求数据修订检查，不自动分析或保存项目，旧图身份不可核实则明确列为省略 |
| 峰重建与秩一分解 | `util.denoise.peak_recon()` / `r1_decomposition()` | 无应用/HTTP/Vue 工作流 | TOOL-01，工具级输入/科学定义/验证先于界面，不能替换现有提取算法 |
| 互操作/元数据/绘图辅助 | AnnData/H5AD、assign_source_metadata、EIC/质谱 Matplotlib、configure_plotting | Vue 已有保存重载、稳定样本元数据、Plotly 原始谱及导出 | 保留 Python 专用辅助接口，功能等价覆盖不要求逐函数建立控件；恢复原始输入和方法默认值分别管理 |

当前优先审阅入口：`frontend/src/stores/workspace.ts` 的 run/read 与任务状态，
RawPage/ExtractionPage 的 KeepAlive 轮询，AnalysisPage 的计算→刷新→绘图，
`application/web_workspace.py` 的工作区锁与 `web_projects.py` 的候选复制，`web_analysis.py` 的同步操作，
`web_results.py` 的保存/导出。它们是 M1/M2 的代码审阅起点，不能仅凭文件较长认定性能瓶颈。
当前层次继续保持，复杂页面可随交互修复拆分组件；性能优化须有输入规模、实际参数与测量证据。

新增能力按领域算法→应用层候选/结果管理→HTTP 契约→Vue 交互→保存/下载与重载的顺序接入。
当前 Operation/结果类型白名单不会因新增 Python 方法自动扩展；须逐项检查工作区修订、
矩阵/特征/参数依赖、可下载状态及旧快照兼容。数值、应用失败恢复、HTTP 和浏览器交互分别验证，
不要用通用“运行任意函数”接口绕过参数与路径边界。

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

日常本地检查与 CI **只运行修改或受影响的块**。先看计划，再执行；没有修改且不受影响的块跳过。
逐块整理时先对准备修改的块建立基线，修改后验证该块与受影响部分；已经通过且后续未受影响的块不重复运行，
不在结束时默认再跑全量。`-W error` 继续将警告作为错误。

```bash
# 默认比较 HEAD 与暂存区/工作区，并纳入未跟踪文件；只输出计划
uv run --no-sync python scripts/test_blocks.py
# 执行计划中的检查（使用已同步的开发环境）
uv run --no-sync python scripts/test_blocks.py --run
# 比较完整提交范围；本地 feature 分支可将 --base 指向共同祖先
uv run --no-sync python scripts/test_blocks.py --base origin/dev --head HEAD
# 显式指定块，不混入当前工作区的其他改动；适用于逐块基线与验证
uv run --no-sync python scripts/test_blocks.py --block spectra --phase python --run
# 只查看指定文件的影响，不需要实际修改文件
uv run --no-sync python scripts/test_blocks.py --files frontend/src/features/monitor/MonitorPage.vue
```

唯一映射为 [`tests/blocks.json`](../tests/blocks.json)，选择器为
[`scripts/test_blocks.py`](../scripts/test_blocks.py)。每次输出选择、原因和跳过的块；
`--write-plan` 保存计划，`--plan` 复用同一份计划，`--phase` 只执行其中一个阶段。
`--files` 可提供明确的文件集合，`--block` 可重复。移动文件同时检查旧/新路径，不能只看重命名后的路径。
选择器使用目录/文件列表与显式依赖关系，不使用全局 `-k`。

### 测试目录与块

```text
tests/
  support/       # 显式导入的小型谱、项目、脂质与认证/HTTP 构造
  domain/        # 数值定义、数据容器、RAW/XML、统计、注释与绘图
  application/   # 参数、预览/提取、持久任务、项目、回收和结果生命周期
  api/           # HTTP 请求、权限、修订、下载及必要贯通检查；局部 conftest
  tooling/       # 发布/回滚、扫描、快照、选择器、文档与 Notebook
  blocks.json    # 本地/CI 共用的文件 → 块及依赖方映射
frontend/tests/  # fixtures.ts、server.py 和按交互划分的 spec
```

| 块 | 保障范围 |
|---|---|
| `spectra` | 谱 I/O、峰/细胞、SNR、ppm、RAW 协议/资源回收与 RAW/XML 等价 |
| `data` | 矩阵/元数据、合并、H5AD/旧目录、原子写入、归一化及零分母 |
| `analysis` | 统计、分组验证、监督诊断、统一降维 |
| `annotation` | 质量候选、同位素、规则、数据库下载/完整性 |
| `plotting` | Notebook 绘图、轨迹、趋势及网页显示精度 |
| `processing` | 原始预览、参数、缓存、持久 worker、提取审核、质量产物及处理 CLI |
| `projects` | 项目/快照、恢复起点、修订冲突、路径与回收保护、UTF-8 持久边界 |
| `workbench` | 变换事务、结果失效、历史层与潜变量持久化 |
| `api` / `api-raw` / `api-lipids` | 工作区/样本/分析/保存下载、原始谱与提取、脂质 HTTP 契约 |
| `auth` / `monitor` | 认证/服务器配置及管理员监控 |
| `tooling` | 发布阻塞与回滚、扫描、上游快照、跨平台导入与分块选择 |
| `docs` / `notebook` | 受影响文档的链接/锚点与 Python 示例；Notebook 清洁及语法 |
| `browser-*` | 项目、工作流/分析、导航、登录/普通 HTTP、监控、脂质及 AI；实际 spec 与影响范围以 blocks.json 为准 |

数值断言集中领域层，应用层验证失败/恢复和生命周期，API 验证边界/序列化/状态，浏览器保留真实交互。
不同边界不能只因功能同名而删除；共享构造从 `support` 导入，不从另一个测试文件导入。
根目录不放通用重型 fixture，HTTP 工作流 fixture 只在 `tests/api/conftest.py` 注册。

### 选择规则与 CI

- 测试文件变化只运行其所属块；共享 fixture 变化只运行实际使用它的块，不扩展到业务依赖方。
- 业务源码变化按映射扩展到使用者；公共数据层、接口/工作区契约、依赖锁文件会扩大范围，并输出原因。
- 纯前端变化不运行 Python 测试；按功能选浏览器 spec。共享组件、路由、状态/客户端及前端依赖会影响全部浏览器块。
  Prettier 配置单独变化只检查前端格式，不运行构建或浏览器测试；格式规则/前端依赖变化时检查全部前端格式输入。
- 文档变化只检查相关文档；链接目标变化同时检查引用它的文档。文档检查器本身改变时检查全部维护文档。
  Notebook 独立成块，普通 Markdown 改动不执行 Notebook 检查，更不执行其中的实验代码。
- 已知目录中的新文件若缺少细分映射，明确报告 `UNMAPPED` 并选择该区域的保守范围；其他未知路径报错，须补映射。
  不能静默当作无影响，也不把每次常规改动都退回全量。

CI 保留 dev/main/refined push 与 pull request 触发；手动 `workflow_dispatch` 可显式运行全部测试。`changes` 只计算一次计划：PR 使用目标分支与 PR head 的
共同祖先到 head；push 使用事件的 before→after，包含本次所有提交；新分支首次 push 检查该分支全部文件。
比较失败会使 CI 失败，不能解释为空差异。Python job 保留 3.11/3.12，只运行选中的 Python 块；
checks job 在 3.12 执行相关文档、改动 Python 文件的 Ruff 与源码扫描，按需安装 Node、格式检查、类型检查和构建一次前端，
再运行选中的浏览器 spec、构建相关发行包及扫描产物。源码只扫描改动文件一次，产物扫描不再重扫源码；
独立的完整源码/历史审计仍保留。测试依赖取所选块的 extras 并使用锁文件，不安装 Notebook 工具链或升级依赖。
发行包包含静态资源，相关包输入变化时前端构建是必要前置；测试或 Markdown 单独变化不构建发行包。

浏览器自动启动 5117 的隔离服务，使用临时项目和合成数据，不访问开发或生产实验。
`SCMM_E2E_PORT`、`SCMM_TEST_PYTHON`、`SCMM_CHROMIUM` 可指定端口、解释器与已有浏览器；
`SCMM_TEST_STATIC_ROOT` 可指向暂存 Vite 资源。首次浏览器执行前安装依赖及 Chromium：

```bash
npm --prefix frontend ci
npm --prefix frontend exec -- playwright install chromium
```

截图、trace 和报告保留在被忽略的测试输出目录。合成检查不替代真实实验、用户验收或远端 CI。
原始预览使用独立进程、提取使用持久 worker；其余 HTTP 计算持有工作区锁。
`/api/v1/runtime` 的未保存/繁忙工作区与页面活动证据继续约束发布，不因测试分块而放松。

### 手动全量入口

仅在明确需要完整检查时执行；日常修改和本轮整理不默认执行：

```bash
uv run --no-sync python scripts/test_blocks.py --all --run
# 只运行全部 Python 测试并统计覆盖率
uv run --no-sync python -m pytest -W error --cov=scMM --cov-report=term-missing
```

单文件诊断仍可使用 `uv run --no-sync python -m pytest tests/domain/test_data.py -q -W error`。
从仓库根使用 `python -m pytest`，确保本地 `scripts` 与 `tests.support` 可导入。
依赖同步、真实 RAW 对照及规模检查按实际改动单独执行，不作为每次运行的隐含前置。

## 脂质注释规模检查

网页领域计算在 `util/lipid_annotation.py` / `lipid_isotopes.py`，声明式规则在 `lipid_rules.py`；
数据库下载、摘要及加载在 `application/lipid_database.py`，事务/版本/审阅/导出在 `web_lipids.py`，
严格 HTTP 契约在 `api/lipid_schemas.py`，页面组件在 `frontend/src/features/preprocess/LipidPanel.vue`。
不通过任意函数执行接口，不改变 `CyESIData.deisotope()` 的原有算法或默认值。

质量搜索对数据库排序索引二分查找，仅对匹配的母峰/理论同位素/观测特征计算关系；
质量/同位素搜索不构造特征平方矩阵。相关网络在 `util/lipid_network.py` 按样本使用临时特征平方相关矩阵，
只对绘图阈值以上或化学关系对计算共同检出相关；审阅感知的饼图/分子映射/显示投影在 `lipid_network_views.py`。
节点显示上限不减少辅助证据计算，完整候选包括同质量异构记录，公式分布缓存复用，不以截断候选节省资源。
按用户确认，本轮限于 ≤500 特征的同步请求，不开展 M1/M2；不能据此宣称其他重任务已后台化。

合成规模报告可在数据库已准备的环境复现：

```sh
python tools/benchmark_lipid_annotation.py --cells 3000 --samples 10 --features 500 --output /tmp/lipid-3000.json
python tools/benchmark_lipid_annotation.py --cells 10000 --samples 10 --features 500 --output /tmp/lipid-10000.json
```

输出仅为参数/规模/耗时/进程峰值内存与数量，不保存矩阵。实际报告见
[3,000 × 500](validation/lipid-annotation-synthetic-3000x500.json)和
[10,000 × 500](validation/lipid-annotation-synthetic-10000x500.json)。耗时分开记录数据库首次加载与领域计算，
峰值内存包含解释器、数据库、矩阵和工作区输入副本，不等于单个算法数组占用；尚不包含完整 HTTP 保存流程峰值。
用户选择手动验收，不以这些合成结果声明真实样本准确率。

相关网络的当前合成规模证据另见
[3,000 × 500 网络报告](validation/lipid-network-synthetic-3000x500.json)和
[10,000 × 500 网络报告](validation/lipid-network-synthetic-10000x500.json)。复用上述命令并更换输出文件名可复现；
本次领域总耗时包含相关网络，报告新增两层边对数、化学关系数和注释版本 JSON 大小。
图表/网络模块在安装包内，版本数据随 H5AD/项目保存；前端不持有矩阵或执行化学判定。

专项检查为 `tests/domain/test_lipid_annotation.py`、`tests/api/test_web_lipids.py` 和 `frontend/tests/lipids.spec.ts`，
覆盖双侧比例边界、加合物组成、并列/重复质量、失败原子性、版本/预设、过期下载及保存重载；
浏览器使用本地合成 SDF，不访问或下载真实数据库，也不打开用户项目。

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
  双重校验；TIC/EIC 等领域计算保留在 `application/`，网页页面与路由只管理边界和展示。
- 旧任务输出通过 `OutputCatalog` 限制目录；当前项目通过 `ProjectStore` 固定根目录及产物路径校验，
  保存时先写快照、后发布清单，并检查修订冲突。批量提取必须在独立 worker 中执行，
  使用持久状态恢复。细胞预览使用 spawn 独立进程，读取、共同特征、完整提取和缓存均在进程中完成；
  网页轮询 future 与阶段状态，核对会话项目、样本/参数代次及文件身份后接收结果。
  子进程不得修改活跃项目或前端对象；失败、关闭和过期结果不能启用下载或确认。
  任务完成后释放工作进程；工作进程重新读取原始文件，页面已加载的原始谱仍保留，需计入额外内存。
  每会话只运行一个预览，跨会话与提取批次的资源限制尚未统一。
  原始文件打开、单扫描、分析与保存仍同步，剩余后台化见[待办清单](roadmap.md)。

## 兼容性回归边界

以下编号用于相关修改及上游移植的回归审阅，不表示未完成缺陷：

- **REG-01**：保留 group_key holdout/CV、SMOTE 最小样本及非有限输入检查，失败必须报错。
- **REG-02**：保留旧目录兼容、H5AD raw/层/嵌入保真、原子发布和默认防覆盖，不整体替换数据容器。
- **REG-03**：保留 XML 完整性、RAW 超时/协议/资源回收、归一化零值、SDF、reference ppm 与 SNR 定义；直接 reader 失败不隐式转换。
- **REG-04**：保留 frame_id/ms_level/native_id 已验证的元数据路径。
- **REG-05**：保留持久任务、审核合并、主动保存及存储目录边界。
- **VAL-04**：holdout PR/AP、校准和 Brier 不可在反复调参后继续解释为独立测试；细胞数不等于生物重复数。

## 分析功能接入指南

本节是网页分析扩展的主要接入说明，示例全部来自已有四类分析，不增加演示算法。
先核对实际代码与分支；能力限制见[能力覆盖](#前后端能力覆盖)，科学解释见[分析说明](analysis.md)。
下文 `frontend/` 相对仓库根，Python 路径带 `scMM/`。不要仅凭注册导航就声明后端能力已经接通。

### 先判断扩展类型

| 类型 | 修改位置与边界 | 验证重点 |
|---|---|---|
| 已有参数扩展 | 对应 `modules/*/*Panel.vue`；`useAnalysisSettings` 的默认值、序列化、恢复；计算参数再检查 `workflow_schemas.py` 对应模型、`parameters.py` 帮助/预设与领域函数 | 默认值、非法值、旧设置恢复、参数归属及依赖失效；纯提示修改无需重走算法流程 |
| 新图形或展示 | 模块模板、既有 `PlotView`/`DataTable`；只有新增服务端图时修改 `Plot.kind`、`PLOTS`、`analysis_plot`、`plot/workbench.py`、`PlotKind` 和结果图映射 | 绘图失败重试、展示不重算检验、保存只读图、过期图不能下载、响应式布局 |
| 完整分析能力 | 按下述领域 → 应用 → API → Vue → 保存重载与导出逐层接入；按需创建模块 | 数值、原子性、依赖生命周期、严格接口、交互、保存导出贯通 |

例如调整现有网络 `top_features` 的表单，不要求再造一个算法或导航模块；火山图的 `labels` 是展示参数，
不能因此重新跑差异检验或清除 Marker。`network` 是完整能力的现有参考。
已有 `plot/embedding.py::register_dim` 只扩展该 Python 绘图入口，**不会自动开放网页降维方法**；
网页使用 `analysis/embedding.py::reduce_dimension` 和严格的 `Reduction.method`，需要分别接通。

### 前端入口与职责

| 文件/符号（均在 `frontend/src/`） | 职责 |
|---|---|
| `features/analysis/AnalysisPage.vue` | 页面标题、公共图例/设置、宽屏导航与窄屏选择；提供页面级上下文；不放领域表单 |
| `features/analysis/registry.ts::analysisModules` | 稳定 ID、中文名称、分组、组件入口及输入要求说明 |
| `features/analysis/types.ts` | 操作/结果/图形类型、模块与传输接口、`analysisKey` |
| `features/analysis/composables/useAnalysisSettings.ts::useAnalysisSettings` | 表单默认值、`settings` 序列化、`resetSettings` 和 `restoreSettings` 旧设置兼容 |
| `features/analysis/composables/useAnalysis.ts::useAnalysis` | 草稿、项目/数据身份、摘要刷新、依赖失效、公共执行、报告与绘图；不持有矩阵/模型 |
| `features/analysis/composables/useAnalysisContext.ts::useAnalysisContext` | 模块取得页面上下文；只能在分析页下使用 |
| `features/analysis/results.ts` | `operations` 操作→结果/默认图；`resultPlots` 结果→所有关联图；`resultDownloads` 完整报告文件名，结果页复用 |
| `features/analysis/modules/{embedding,differential,network,supervised}/` | 四类真实表单、输入提示、运行按钮及图表报告布局 |
| `features/analysis/components/ResultTable.vue` | 仅显示后端仍认可的表格；复用全站 `components/DataTable.vue` |
| `stores/workspace.ts::analysisTransaction` | 整条分析执行链持有 `busy`，带工作区修订写入，核对响应身份与预期修订 |

模块按“输入与参数 → 运行操作 → 图表与报告”组织；复杂表单留在模块，高级参数折叠。
参数用英文名称，帮助用中文 `FieldLabel`/`HelpTip` 悬停展示。复用 `PlotView` 的图例、缩放和下载，
不要再实现一套格式化或图形下载；实际重复的分析报告用 `ResultTable`，不为假想复用建立万能表单。

创建面板后在 `analysisModules` 注册，现有网络条目为：

```ts
{ id: 'network', name: '相关网络', group: '探索',
  component: NetworkPanel, requires: ['matrix'] }
```

`requires` 当前是可审阅的声明，**不是自动校验引擎**。模块仍需根据 `info.layers`、`observations`、
`embeddings`、`live_results` 禁用不适用操作并说明原因，后端最终验证真实输入。
页面通过 `v-show` 保留模块状态，模块须有单个根节点；切换导航只改 `tab`，不启动计算或重绘。
现有图在模块不可见时卸载 Plotly 展示，图形描述仍在公共状态中；这不等于保存到磁盘。

网络面板使用下述现有调用方式：

```ts
const { network, store, info, execute, has, loadWithPlot } = useAnalysisContext()
// 按钮禁用条件包含 store.busy；layer 选项来自 info.value?.layers。
await execute('network', { ...network })
if (has('network')) await loadWithPlot('network', 'network_plot')
```

`execute` 负责计算→更新工作区→刷新有效结果→读取报告→绘图。独立读取用 `loadResult`，
独立重绘用 `draw`，组合读取/重绘用 `loadWithPlot`；这些都复用事务锁，不能在模块中自行拼接
多个各自释放 `busy` 的 `store.mutate/read/command`。计算失败保留先前已提交状态；成功替换的结果
清理对应旧展示，后续失败提示“计算已完成，结果已保留”，可读取/重绘。公共“重新读取分析状态”
用于恢复摘要读取；请求超时不会自动重放写操作，须先读取实际状态。

### 参数、草稿与恢复

| 所属模块 | 自有参数 | 明确共享的依赖 |
|---|---|---|
| 降维 / 聚类独立板块 | `reduction`、`usePca`、`cluster`；嵌入/着色选择 | 聚类使用独立的 `cluster.use_rep/n_neighbors/random_state` |
| 差异与 Marker | `diff`；`volcano`、`selectedFeatures`、`hideZero` 为显示状态 | Marker 使用 `diff.group_key/method/layer`，不依赖两组选择 |
| 相关网络 | `network.method/min_abs_correlation/top_features/layer` | 不依赖差异分组或后续 layer 编辑 |
| 监督与 SHAP | `train`、`validation`、`ldaSolver`、`latentKey`、`shap` | SHAP 使用 `train.random_state` 作为 seed，并依赖当前可执行监督结果 |
| 页面公共 | `legend` | 图例只改变展示，不使统计结果失效 |

恢复顺序为：清空全部表单和展示选择 → 配置默认值 → 当前项目设置（同项目草稿优先）→ 校正失效输入选择。
`restoreSettings` 对旧项目中缺失的 `train.random_state` 使用旧 `reduction.random_state`，
缺失的 `network.layer` 使用旧 `diff.layer`；迁移后分别管理。更早的 `views.settings` 字段由
`web_analysis.py::analysis_settings` 转为当前分组设置。不要因新增默认值覆盖已有项目的显式选择。

新增字段应同时检查四处：初始默认值、`settings` 输出、`restoreSettings` 的类型/缺失兼容、
`resetSettings` 的项目切换恢复；计算参数还要更新对应依赖 watcher。表单草稿放 `store.analysisDraft`，
绑定项目路径；切换项目清除草稿。切换数据身份重置面板，正常新增嵌入或修改元数据时只刷新有效性。
页面维护草稿的表单及待恢复视图按用户、工作区和项目隔离；任一身份切换清空缓存并使排队恢复失效。
读取草稿期间有新输入或工作区修订变化时，不再应用迟到草稿；延迟恢复控件同样保留用户刚输入的值。
“应用视图设置”只写内存项目设置；“保存项目”由 `store.mutate('/project/save')` 先写当前分析草稿，
再执行项目快照保存。模块不得自动保存项目。搜索/分页等临时选择不必持久化，也不应成为科学参数。

### 领域、应用与严格 API

1. **领域算法**：数值函数放 `scMM/analysis/`，需要容器能力时通过稳定门面接入。
   网络参考 `statistics.py::feature_correlation_network`；验证矩阵/layer、有限值、维度、参数范围、
   空输入和零分母。可选依赖在对应功能调用时导入并提供明确缺失提示，不增加全站启动依赖。
2. **应用编排**：`application/workbench.py::AnalysisWorkspace`承载数据 token、
   输出与溯源；现有方法为 `network`、`differential`、`train` 等。网页通过
   `web_analysis.py::AnalysisWorkflow.run_operation` 使用 `web_projects.py::project_candidate`，执行成功后一次发布。
   失败不得修改原项目；会修改已有模型的操作参考 `explain_shap` 对结果的额外深复制。
   输出嵌入/obs 键须验证合法性和冲突，参考 `reduce/cluster/save_latent`，不能覆盖已有键。
3. **严格 API**：`api/workflow_schemas.py` 增加/调整 `Controls` 子类及 `OPERATIONS`，并核对
   `Operation.operation` Literal；`options_for` 校验 options。图形对应 `Plot.kind`、`PLOTS`。
   `api/routers/analysis.py` 只处理请求和返回，不写数值计算；应用层 `ANALYSES` 也须明确允许。
   注册 Vue 或加入任意 Python 函数不会获得 HTTP 执行能力；保持禁止额外字段和操作白名单。
   `Train.model_params` 使用逐模型字段白名单和组合/训练折约束，不能作为任意函数调用入口。
4. **Vue**：补齐 `results.contract.json`、`PlotKind` 与模块；`AnalysisOperation/ResultName` 从前端显式契约的键推导，对应模块调用公共流程；
   仅新能力需要独立导航时才注册新模块。配置帮助/预设入口在 `application/parameters.py`、`preferences.py`。
5. **保存重载与导出**：`workbench.py::save_h5ad` 经 `result_catalog.py::serialize_reports` 组装 `reports_json`，
   `projects.py::ProjectStore` 管理快照和视图，`web_analysis.py::result_value/result_view/analysis_plot`
   读取实时或只读结果；`web_results.py::ResultWorkflow.download_content` 导出完整内容。
   在结果目录注册名称/关联图/元数据依赖/下载和序列化规则，同步前端显式 JSON 映射及 API 白名单；默认分页表不是完整导出。
   不保存可执行模型，不在 JSON 中舍入科学值，不把 Graph/模型塞进前端或快照。

现有操作示例：`Network` API 模型约束 threshold 0～1、top_features 1～1000；应用层只在
候选中调用 `network`；领域函数返回图和相关矩阵；网页只读边表与 Plotly 图描述，完整边表按 CSV 下载。
前端注册、API 类型和 Python 映射有意保持显式，尚无自动生成的跨语言协议或动态插件加载器。

### 输入、输出及生命周期声明

接入 PR/变更说明必须写清下表；它是审阅模板，当前没有自动读取该模板的依赖引擎。

| 声明项 | 现有示例与必须核对内容 |
|---|---|
| 输入 | 网络：当前 X 或 `network.layer`；差异：矩阵/layer + group 列和两组；降维：X/指定 obsm；监督：矩阵/layer + label/group；SHAP：实时监督模型 |
| 参数与随机性 | 参数归属、默认值、单位、范围、seed；降维/聚类记录 history，报告记录各自 parameters/分组信息；不要宣称所有结果已有统一溯源模式 |
| 输出 | 降维写 `obsm[store_key]`，聚类写 `obs[key]`；统计写 `results[name]`，监督写内存 analyzer；图写 `views.figures[kind]`；说明新键及冲突策略 |
| 依赖与失效 | 矩阵变换清下游结果；元数据仅按使用的字段清理；train 重算清 SHAP；参数编辑按对应 watcher 清结果；纯显示编辑不清统计 |
| 保存与重载 | 数据/嵌入/元数据、起点、报告与已生成只读图可保存；模型不保存；重载后 SHAP 新计算和潜变量输出须重训；网络/监督图的重载依赖已保存图，不能承诺重建任意图 |
| 导出 | 指定完整表/JSON/嵌入与图的下载方式，检查后端有效性；界面分页和格式化不能截断导出或降低精度 |

**工作区修订与数据修订不同**：`BrowserWorkspace.revision` 每次成功写入（包括绘图、设置）递增，
用于防止过时页面写入；`AnalysisWorkspace.token` 是 `(dataset_id, revision)`，表示数据身份与数据变更。
绘图不改变数据 token。新增嵌入/聚类会增加数据修订，但 `_commit(clear_derived=False)` 重绑定无关结果，
不能见到数据修订变化就删除全部展示。矩阵变换则清除派生结果。

后端有效性入口为 `AnalysisWorkspace.result`、`AnalysisWorkflow.result_value`；
`sync_sample_metadata` 和 `web_workspace.py::sync_metadata` 按依赖字段同步实时/已保存报告和图，
`result_catalog.py` 的关联图与后继结果规则清理；新增结果须补齐目录、前端契约及下游依赖。
`analysis_info.results` 用于页面可用性，`live_results` 区分可执行对象；页面隐藏按钮不能代替下载校验。
`download_content` 必须继续通过有效性入口。纯图例、标签数量、特征显示等变更不清除统计结果。

前端摘要/特征读取使用请求代次及项目/数据身份，报告和图在同一事务中核对工作区身份与预期修订。
不要在未核对身份时应用迟到的成功或错误响应。`requires` 声明和 watcher 不代替后端有效性。
现有依赖并非通用 DAG；新增依赖要显式补齐保存、重载和失效处理，不能只改前端映射。
分析仍在同步 HTTP 内完成，锁不等于后台任务、取消计算或可断线恢复的任务协议；后台化见 roadmap。

### 按风险选择接入检查

- **算法/输入变化**：小型合成数值对照、边界/非有限值、缺可选依赖、seed 重现；真实实验另记，不能以浏览器成功代替。
- **状态/输出变化**：非法输入与计算失败保留旧状态、图失败保留新结果并可重试、输出键冲突、矩阵变更清理及无关元数据保留。
- **API 变化**：额外字段/非法操作拒绝、参数类型/范围、工作区修订冲突、越权身份与候选原子性。
- **前端流程变化**：四模块切换不计算、草稿与旧设置恢复、项目/数据切换重置；重复点击、报告/绘图等待期间互斥、旧成功/旧失败响应；宽屏与 700/390px，控制台无运行错误。
- **生命周期/存储变化**：主动保存后重载报告/图、模型只读限制、旧结果与图下载拒绝；完整 CSV/JSON/H5AD 精度，分页不影响导出；依赖字段和纯展示变化分别覆盖。
- **文档**：使用行为改 `workflow.md`，默认值/单位改 `parameters.md`，科学解释改 `analysis.md`，持久化改 `data-output.md`；本节保持唯一主指南，更新 CHANGELOG/roadmap 的验证与待验收状态。

现有定位：`tests/domain/test_analysis.py`、`test_analysis_views.py` 验证算法/图；
`tests/application/test_workbench_state.py` 验证生命周期；`tests/api/test_web_api.py`、`test_web_workflow.py`
覆盖严格契约、事务、保存重载/下载；`frontend/tests/analysis.spec.ts` 覆盖设置、导航、互斥、失败重试与迟到响应，
`workflow.spec.ts` 贯通四类分析、保存重载和完整导出。共享 store 改动还要选择导航/认证/其他读请求的受影响回归。
类型/构建为 `npm --prefix frontend run build`，文档链接/锚点为
`uv run --no-sync python -m pytest tests/tooling/test_documentation.py -q -W error`。
按[分块验证](#完整验证)选择受影响检查；仅改帮助文案或已有显示参数时，不机械重跑全部算法和真实实验。

## 添加归一化方法

归一化方法通过注册表扩展：

```python
from scMM.util.normalize import register_norm


@register_norm("custom")
def norm_custom(X, params):
    scale = params.get("scale", 1.0)
    return X * scale
```

新方法应验证二维输入、零分母、NaN/Inf 和参数类型，并在 `tests/domain/test_normalize.py` 添加测试。

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

完成相关开发检查后，更新 5007 开发服务供用户验收，保留工作区修改。用户明确验收通过后，
再提交、推送并部署生产；执行顺序见 [发布、更新与回滚](installation.md#发布更新与回滚)。

先完成本次改动涉及的[分块验证](#完整验证)；包输入改变时构建发行包，再用本次 wheel 检查独立安装入口。
核对 dist 中选中的文件确为本次产物：

```bash
uv run --isolated --no-project \
  --with "$(find dist -maxdepth 1 -name '*.whl' -print -quit)" \
  scmm-process --help
```

提取/读取链改变时，还应在受支持的 Python 版本和代表性 mzML/mzXML 文件上完成相关端到端验证。

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

## 认证与服务器资源边界

`application/auth.py` 管理 SQLite 账号、Argon2id 密码、随机会话摘要、一次性凭据、登录限速及安全日志；
`application/identity.py` 只承载请求身份上下文，不给核心数值模块引入认证依赖。
`api/app.py` 统一保护业务接口并检查管理员权限、完整来源和会话绑定 CSRF；静态页面及最小健康检查可匿名访问。
`api/routers/auth.py` 提供登录、改密和管理接口，认证配置缺失时拒绝构建应用；没有匿名开关。
`web_workspace.py` 在工作区访问锁内复核所有者，团队共享磁盘项目仍使用原有修订和原子快照契约。
账号数据库不入项目快照；原生 Python/CLI 使用者仍由服务器操作系统权限管理。

`application/server_config.py` 解析仓库外资源配置，`api/admin_cli.py` 提供显式初始化和离线恢复。
必需目录在启动时检查，注释及 RAW 可选资源在功能使用时检查；服务器模式下失效路径不回退到其他位置。
普通启动不创建缺失目录，不自动扩展数据白名单。
部署布局使用[通用模板](../config/environments.example.json)，网页资源使用[独立模板](../config/server.example.json)；
优先级、环境变量和命令见[安装部署](installation.md#访问与路径配置)。

认证专项运行 `PYTHONUTF8=1 .venv/bin/python -m pytest tests/api/test_authentication.py tests/api/test_server_config.py -q -W error`。
原有 HTTP 回归使用真实临时数据库及登录，不绕过中间件；浏览器使用隔离合成账号，不读取线上凭据。
同账号重新登录可继续仍有效的内存工作区，不保证恢复过期工作区或服务重启前的草稿。

## 开源敏感信息检查与历史清理计划

当前文件检查：`python scripts/check_sensitive.py`；全部本地可达历史审计：
`python scripts/check_sensitive.py --history --report /tmp/scmm-security-audit.json`。
检查代码、文档、CHANGELOG、Notebook 输出、验证报告，以及 `dist/`、`build/` 和服务静态资源；
zip/wheel/sdist 在内存中检查，不解压到工作区。规则覆盖个人目录、内网地址、常见凭据格式、私钥、带凭据 URL、
字面量密码/密钥赋值及凭据文件名；超过扫描上限的压缩包报未完成检查，不当作通过。
输出只有类别、文件、行号和历史对象摘要，不输出命中值。模式扫描无法证明不存在未知格式的敏感信息，发布前仍须审阅。
CI 检查本次变更源码和按需构建的产物；历史单独记录，不能把既有历史问题隐藏成当前源码通过。

本轮按用户确认只审计历史并准备计划，不改写提交、不更新远端；脱敏摘要见
[开源审计报告](validation/open-source-audit.json)。历史仍含个人路径、内网地址及带输出的旧 Notebook。
当前文件脱敏不会移除这些 Git 对象；GitHub 旧提交、引用、克隆和缓存也不会因此消失。
当前未命中所扫描的凭据模式，不能扩展为不存在凭据的结论；未来发现真实凭据必须先撤销或轮换，再处理历史。

后续历史处理需单独审阅以下范围：

1. 冻结协作写入，核对远端分支/标签、本地旧分支、备份 refs 和所有 worktree，创建仓库外私有备份及隔离 mirror。
2. 对拟公开引用执行路径/地址替换，清空历史 Notebook 输出及执行计数，审阅代码单元中的真实路径。
   保留科学定义和数值报告；旧源码快照及归档逐项核对。
3. 在隔离镜像重新扫描全部可达对象，执行文档/Notebook/构建检查，产出旧新提交映射和受影响引用清单。
4. 审阅并另行授权后协调远端引用更新和必要强推，按 GitHub 要求处理旧 PR/缓存引用，通知协作者重新克隆。
   重写本地分支不能清除远端、备份、reflog 或第三方克隆，不承诺彻底删除已公开数据。
5. 用户确认迁移可用后再评估本地旧 refs、reflog、备份和对象回收，不自动删除恢复材料。

依据 [GitHub 敏感数据移除说明](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)。
认证参考 [Argon2-cffi](https://argon2-cffi.readthedocs.io/en/stable/howto.html) 及
[OWASP 会话管理](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)。


## AI 助手边界

`application/ai_config.py` 管理按用户隔离的 Fernet 配置，`ai_client.py` 管理地址策略、DNS 固定连接与
Chat Completions SSE 解码，`ai_summary.py` 是自动出站字段的唯一白名单；`api/routers/ai.py` 只处理认证边界、
请求限额和流式生命周期。前端 `features/assistant/` 独立承载账号设置及常驻面板，聊天按用户/上下文加密持久化于独立 AI 数据库。
不把消息、凭据或摘要写进团队项目快照、浏览器持久存储或审计正文。

工作区在已有科学锁内完成事务后发布独立摘要快照，失败保留旧摘要，失效随已提交修订一起发布。
`ai_context()` 仅取得管理器和独立摘要短锁，验证用户归属/有效期后释放，再读取已注册轻量任务状态；
它不调用 `access()`、不读取原始谱、不执行算法。网络等待全程不持科学工作区锁。
摘要记录完成时间、工作区修订、数据修订及独立快照代次，运行操作与完成结果分开；缺失/失效结果明确标记。
批次状态仅输出运行/等待审核；无细分进度不产生百分比或 ETA。旧/畸形导入元数据摘要失败时关闭该摘要，
不得使科学事务失败或向上游转发原始异常。

新增摘要字段必须按语义逐字段提取，数值仅接受有限值，字符串限已知方法/模型枚举；
不要复用工作区响应、完整处理历史、日志、项目清单、图表 JSON 或任意递归清洗器。
自定义键、名称、分组及层名不出站。模型验证只取已有 holdout/CV 汇总，差异/Marker 的显著行数以 `fdr < 0.05`
为明确描述阈值，Marker 行数可能跨簇重复同一特征，不冒充独立特征总数。
对话历史只能使用 user/assistant 文本，本轮最新摘要作为 system 数据插入最后问题前，不能被旧结果替代。
每 0.5 秒及每块回答检查登录、工作区代次和个人配置；过期停止并关闭上游，不重放请求。

测试块 `ai` 用带敏感标记的合成数据及模拟上游验证实际出站载荷、加密/隔离、长计算期间提问、
版本/登录/配置失效、流分块、错误脱敏与失败恢复；`browser-ai` 验证设置、跨页、停止、清空和刷新生命周期。
测试不能依赖真实 Key。真实服务联调和用户验收另记，不能把模拟回答作为科学准确性证据。
协议依据：[Chat Completions 流事件](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events)、
[API 认证](https://developers.openai.com/api/reference/overview)。

## 管理员监控边界

`application/monitor.py` 在独立线程采样，`monitor_probe.py` 使用仅依赖 psutil/标准库的限时子进程读取固定布局元数据与磁盘容量，
不导入科学流程、不遍历谱图/快照树、不读取 H5AD。工作区清单和各工作区锁均只尝试非阻塞读取，不调用 `access`、`_prune` 或复制矩阵。
锁冲突、不可读目录、元数据异常、孤立 worker、采样超时均保留未知证据，不能产生零值成功结论。
`monitor_store.py` 将监控历史、页面租约摘要和账号最近访问单独保存；旧实例页面在新心跳之前保持待确认。
`monitor_presence.py` 计算保守更新判断；`monitor_peer.py` 独立读取配置的生产状态并校验协议、时效、计数及一致性。
HTTP `/presence/register` 与 `/presence/heartbeat` 为登录页提供受限租约，仍校验同源标记/来源，限制路由、字段、容量及注册频率，
心跳须持有对应随机租约，关闭记录不允许迟到心跳重新打开。所有明细、历史和事件接口均仅管理员可读。
任务提交记录请求身份；历史任务无提交人时明确显示“未记录”。页面/历史数据不是部署授权或实验用户验收证据。

专项检查：`PYTHONUTF8=1 .venv/bin/python -m pytest tests/api/test_monitoring.py tests/tooling/test_environments.py tests/api/test_server_config.py -q -W error`，
浏览器回归包含 `frontend/tests/monitor.spec.ts`；测试仅使用临时目录和合成数据。普通采样不发业务请求、不写项目文件。
工作区满额/计算锁占用不影响直接访问监控。前端轮询独立于实验 busy 状态，离开监控页停止轮询，旧响应不覆盖新页面状态。


首次认证迁移使用 `release --migrate-auth`，前提及人工维护窗口证据见[安装部署](installation.md#监控初始化与生产只读检查)。
该路径仅支持旧版、不能覆盖新监控状态；测试覆盖非零/非法旧计数、新协议拒绝及安装/同步/健康失败后旧启动器和代码共同恢复。
常规发布继续使用新协议和时效检查。恢复备份位于仓库外；配置、认证库和监控库不随代码回滚。

### 维护与作图模块

`application/state_codec.py` 明确编码 AnnData/数组/表/图及受审核模型；`recovery.py` 原子发布并校验恢复包，
`maintenance.py` 管理页面握手和维护状态，`maintenance_runner.py` 在独立 systemd 任务中执行重启及配置回滚。
`api/routers/maintenance.py` 只开放认证管理入口。公开维护状态只含收集 nonce/完成标记，完整状态只给管理员。
`frontend/src/api/viewState.ts` 注册可恢复页面状态，`maintenance.ts` 收集已访问页面的参数/图及控件；密码、文件输入和账号配置不进入通用草稿采集。
`plot/export.py` 负责全精度 ZIP 与禁止外部资源/活动内容的 SVG→PDF；`plot/explanations.py` 和 `plot/isotopes.py` 提供可追溯解释图。

原始独立诊断由 `application/raw_diagnostics.py` 有界冻结扫描、`analysis/signal_diagnostics.py` 运行既有秩一/峰工具和构造完整对照图；HTTP 仅校验契约与前后输入身份，Vue 独立组件保存表单/图，不持矩阵或修改提取参数。
