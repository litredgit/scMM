# scMM 代理工作指南

更新：2026-10-09。整理基线：`develop` 的 `1d14ee6`；工作台改进提交为 `14bf335`。
本文提供不依赖旧会话的项目上下文和协作规则。开始任务先核对实际分支、工作区与最新提交；
以下测试、服务和路径记录均有时间边界，不能作为本次验证结果。

## 协作规则：先确认问题，关键进展再提交

- 每次新任务先说明目标、范围和可能需要用户决定的问题。可先做必要的只读核对，
  再将需求、行为、验收方式、数据/服务影响等可能的问题集中列出，请用户确认后推进依赖这些答案的工作。
- 目标是尽量提前消除问题，减少执行中打断，**不是禁止执行中提问**。
  新发现会影响实现或结论的不确定项，直接向用户提问，并说明影响；等待时可继续不依赖答案的工作。
  不把沉默或等待超时当作同意，不自行猜测实验参数、用户验收结论或部署授权。
- 已确认的方案及授权沿用，不在每个命令、常规实现细节或连续执行步骤前重复确认。
  若核对后没有待确认问题，明确说明后按现有授权执行。
- Git 按有完整结果和验证证据的关键进展提交；同一小任务的实现、修正和文档合并提交。
  不为每次编辑、测试或进度更新单独提交。跨阶段大任务按可独立验收的里程碑提交。
- 提交前检查工作区与差异，只暂存本任务文件，保留用户已有修改；提交信息使用 `docs:`、`feat:`、`fix:` 等现有风格。
  push、合并、发布和服务重启按本次已有授权执行，授权不明时直接询问。
- 用中文简洁沟通；完成时交代变化、验证、仍未验收的边界及提交状态。

## 项目是什么

scMM 是处理和分析 CyESI 单细胞质谱数据的 Python 包，当前版本 `0.2.0`，Alpha。
从原始谱构建“细胞 × m/z 特征”矩阵，支持细胞事件识别、峰对齐、预处理、精确质量候选注释、
降维聚类、差异/Marker/相关网络、监督模型与 SHAP、Palantir 和时间/代谢趋势分析。

- 输入：mzML、mzXML；直接 RAW 仅支持 **Thermo profile**，不接受 centroid，不隐式转换为 mzML。
- 核心数据门面：`CyESIData`；分析和网页工作区主要使用 AnnData，保留层、注释、嵌入与处理溯源。
- 入口：Python API、根目录 `scMM_workflow.ipynb`、`scmm-process` CLI、Panel/Plotly 的 `scmm-ui` 网页。
- 当前网页是六步项目工作台：样本 → 原始谱与参数 → 提取审核 → 预处理 → 分析 → 结果与保存。
  旧八页工作台或编号文档仅供历史追溯，不能据其修改当前流程。
- Python 支持 3.11–3.12，本地默认 3.12；依赖由 `pyproject.toml` 和 `uv.lock` 管理。
  .NET 8/Thermo 厂商 reader 是外部部署依赖，`uv sync` 不会安装它们。

## 当前进展与下一步

截至整理基线，工作台改进已经进入本地 `develop`；原实施分支 `feat/user-todo-workbench`
也指向 `1d14ee6`。不要将文档中的“实施分支”理解为尚未进入当前代码。

| 范围 | 当前已实现行为 |
|---|---|
| 项目与任务 | 多样本元数据、参数预检、共同/独立特征、持久批处理、失败继续、重试、停止后续样本、人工审核纳入 |
| 保存与分析状态 | 主动保存、修订冲突检测、完整预处理起点恢复、只读报告/图形重载、依赖变化时分析失效 |
| U-D01–04 | 简洁目录浏览与跨目录多选；name/group/subject/batch 实时同步；仅失效相关分析；完整预览按身份/参数/共享特征复用 |
| U-R01–04 | 可编辑全局细胞类型预设、实际 m/z 默认范围、CPU 默认值；秒/扫描帧联动；时间轴拖选与求和/平均合谱 |
| U-A01–05 | 降维输入及参数、分组优先着色和特征排序、左侧分析子导航、火山图标注/多选与最多 12 个响应式小提琴图 |
| U-G01–04/U-V01 | 英文参数/中文操作、表格与图形样式、显示精度、同源数据下载和 PNG/SVG 导出；独立合成检验环境 |

**当前重点：等待用户验收 10 月 9 日工作台改进，按反馈修正，再决定下一阶段。**
[roadmap 用户清单](docs/roadmap.md#用户指定-todo2026-10-08-已确认)的未勾选项表示用户未验收，
不表示尚未实现；不得未经确认勾选、重复实施或自动展开下一批工程工作。

| 历史证据 | 已记录结果 | 仍需区分的边界 |
|---|---|---|
| 2026-10-09 工作台改进 | 本机 Python 3.12 `pytest -W error` 302 项通过；Ruff/格式/差异、离线锁文件检查、sdist/wheel 构建通过 | 不等于本次重新测试或远端 CI 通过 |
| 2026-10-09 Chromium | 两个合成项目；火山图/小提琴、响应式布局、PNG/SVG、TIC 拖选、合谱 CSV、秒/帧/native ID 检查通过，脚本错误 0 | 不替代真实多样本、大规模 RAW、Windows 或用户验收 |
| 2026-10-05 主服务 | 5006 重启至当时 `1ecd5ce`，首页验收通过；当时回归 305 项通过 | 当前进程版本和在线状态需另查，不能推断已加载 10-09 改进 |

不同日期的测试数量仅为各自历史记录，不直接推断覆盖增减。
README 的 10-08 摘要和 roadmap 页首的 `bc3e35d` 引用未覆盖所有新进展；
最新工作台实现以当前代码、[CHANGELOG 10-09 条目](CHANGELOG.md#用户指定工作台改进--2026-10-09)
及 roadmap 用户验收段为依据。有矛盾时核对代码/证据，无法确定则询问用户。

后续待办统一在 [docs/roadmap.md](docs/roadmap.md) 维护，本文只保留接手必需的边界：

- 优先待验收：真实多样本生物质控、更多 RAW/仪器与批量负载、真实网页全流程、云盘中断恢复、Python 双版本远端 CI、发布物一致性。
- 待设计实现：输入身份检查范围、同步预览/分析响应性、细粒度进度、跨项目资源队列、快照清理、依赖复现、统计门禁复核、网络 origin 策略。
- 可选：自动保存/未应用表单保护、更多聚类参数、实验 PDF 报告。当前离页提醒不等于自动保存。
- 明确暂缓：上游非标准轨迹 ALG-03/04、类别概率空间 R2/Q2、Windows 安装/完整后台任务与 threadpoolctl 补丁。
  恢复前先确认定义、适用范围及验收条件；保留现有 Palantir，不直接移植上游问题实现。

## 代码导航

实现代码在 `scMM/`，不要修改 `scMM-new/` 或 `SCMM-GUI-0.2.0-source/` 来交付当前功能。
它们是上游参考；快照查看/导入使用 [开发指南](docs/development.md#上游源码快照)。

| 要修改的能力 | 首先查看 |
|---|---|
| 网页入口、六步导航、会话与保存交互 | `scMM/ui/app.py`、`ui/cli.py`、`ui/layout.py` |
| 原始谱控件、秒/帧、合谱与项目预览 | `ui/project_views.py`、`ui/raw_components.py`、`application/raw_preview.py` |
| 目录选择、分析控件、图表与显示格式 | `ui/file_browser.py`、`ui/workbench.py`、`ui/analysis_plots.py`、`ui/presentation.py` |
| 项目清单、快照、锁、修订与保存恢复 | `application/projects.py`（`Project`/`ProjectStore`） |
| 提取编排、审核合并与预览复用 | `application/project_batch.py`、`application/preview_cache.py` |
| 预处理、重置、数据身份与结果失效 | `application/workbench.py`（`AnalysisWorkspace`） |
| 参数/预设/路径/后台任务 | `application/parameters.py`、`preferences.py`、`processing.py`、`storage.py`、`tasks.py`、`worker.py` |
| 原始文件读取、网格、峰对齐 | `file/io.py`、`file/readers/`、`file/_spectrum.py`、`file/_alignment.py` |
| 数据装载、变换、合并、保存与 AnnData | `file/data.py`、`file/_dataset_loading.py`、`file/_dataset_processing.py`、`file/_dataset_interop.py` |
| 细胞窗口/SNR、去同位素、归一化与注释 | `util/peak.py`、`file/_deisotope.py`、`util/normalize.py`、`util/annotation.py` 及相邻私有模块 |
| 统计、监督与降维 | `analysis/`；统一降维入口 `analysis/embedding.py` |
| Notebook 绘图、轨迹、趋势 | `plot/engine.py`、`plot/_engine_*.py`、`plot/_trajectory.py`、`plot/_trend_clustering.py` |
| 外部 Thermo helper 与真实对照 | `tools/thermo_raw_reader/`、`tools/validate_thermo_*.py`、`docs/validation/` |

表中 `ui/`、`application/`、`file/` 等路径均相对 `scMM/`。
数值计算放在领域模块，Panel 回调负责会话编排和展示；保持公开 API 和 `CyESIData` 构造入口稳定。
跨数据集合并或预处理先构造完整候选状态、验证成功后一次性提交，失败不能污染当前数据。

## 必须保留的行为与科学边界

- **提取与任务**：处理完成后仍需人工审核并纳入样本，才建立当前矩阵。每项目单批互斥；
  尚无跨项目全局资源队列。停止只阻止后续样本，不立即中断当前读取/计算。
  worker 持久保存状态/日志；预览、分析和保存仍同步执行，阶段进度不能冒充 ETA。
- **项目保存**：主动点击保存；刷新不自动保存编辑。先写快照、后原子发布 `project.json`，检查修订冲突。
  `processing/` 存任务和缓存，`snapshots/` 存当前 H5AD、baseline 和只读视图。
  重载恢复当前数据及完整起点，报告/图形只读，不恢复可执行模型，不提供历史分支或逐步撤销。
- **状态失效**：矩阵变换需使下游结果失效；新增嵌入不误删无关分析，已有嵌入/聚类键不能直接覆盖。
  元数据经稳定 `sample_id` 同步当前数据与重置起点；旧结果其次按唯一名称关联，歧义需人工映射。
  元数据更新保留强度和无关降维，只清除依赖改动字段的统计/模型，并阻止下载过期结果。
- **缓存**：完整预览复用必须同时符合文件身份、处理参数和共享特征定义；缓存产物校验失败应重算。
  当前原始文件身份为真实路径、size、mtime/ctime、inode，产物另做 SHA-256；不能声称原始文件已全量哈希。
- **路径与文件**：原始数据只引用不复制。所有服务器路径经配置根目录和真实路径校验，拒绝路径/符号链接越界。
  保留默认防覆盖、旧目录兼容和 H5AD raw/layers/obsm 保真；导入含 pickle 的旧目录须明确信任。
  不删除活动任务或清单引用的产物；清理前先给出可审阅计划。
- **RAW 与精度**：保留 float64、两遍输入身份检查、协议验证、超时和资源回收；保留 XML 完整性检查。
  已有真实对照主要为 Q Exactive `wt-1`，不能推广为所有仪器/厂商/平台均验收。
- **参数**：API 的 `ref_mz` 必须由实验确定。网页预设为哺乳动物 760.5851、藻类 734.5929、细菌 690.5069；
  全局预设变更不追溯覆盖旧项目。CPU 默认逻辑核数的四分之一向下取整、至少 1，并受可用核数限制。
  首次文件 m/z 范围向外取整到 10 的倍数；保留人工/保存值。显示范围与提取范围分开。
- **数值含义**：`legacy` 与 `snr_v1` 的强度/SNR 定义不同，不能直接当作数值等价；
  `snr_v1` 使用基线扣除和背景噪声。保留零分母、NaN/Inf、参考 ppm、多参考窗口和维度检查。
  网页 UMAP 默认 PCA 20 维输入，小数据非法维数明确报错，不静默截断；API 默认另查函数签名。
- **统计**：细胞数不等于独立生物重复；精确质量注释只是候选，不是结构确证。
  保留分组 holdout/CV、SMOTE 样本数及有限值检查；分组划分不能消除上游插补/特征选择泄漏。
  重复调参后的 holdout PR/AP、Brier、校准结果不能继续解释为独立测试。
- **界面**：参数名/解释英文，步骤/按钮/状态中文；前端 m/z 四位小数等显示格式不能降低计算/导出精度。
  随机算法记录 seed，输出参数需可追溯；可选依赖按功能延迟导入，缺失时明确报错。

## 开发与验证

从仓库根目录使用 uv，不随常规任务升级依赖；仅安装环境时运行同步：

```bash
uv sync --locked --all-extras --dev
```

按改动选择已有相关测试；文档任务运行 `tests/test_documentation.py` 并检查新文件本地链接。
工作台相关测试包括 `test_user_todo.py`、`test_project_ui.py`、`test_projects.py`、`test_project_batch.py`、
`test_workbench_state.py`、`test_extraction_preview.py`、`test_unified_embedding.py`。
修改数值/存储/任务流程须覆盖对应失败与恢复语义，合成测试和真实验收分别记录。

```bash
uv run --locked python -m pytest tests/test_documentation.py -q
git diff --check
```

功能里程碑/发布前完整检查与现有 CI 对齐：

```bash
uv lock --check
uv run --locked ruff format --check .
uv run --locked ruff check .
uv run --locked python -m pytest -W error
uv build --no-sources
```

使用 `python -m pytest`，避免部分环境快照工具导入失败。
CI 在 develop/refined push 与 PR 上执行 Python 3.11/3.12；实际结果需对应提交核对。
不提交原始谱、处理矩阵、H5AD、大体积输出或临时截图；测试优先小型合成数据。
Notebook 保持无执行输出，参数集中且不嵌入个人路径。需要上游快照时先按开发指南检查差异，不能整体替换当前容器。

## 本机服务与验收环境

- 仓库：`/home/crs/scMM`；默认项目根：`/home/crs/data/results`，须存在且可写。
  最新 CLI 支持 `--project-root` 指定独立根；`--output` 仅旧任务兼容，不改变项目根。
- 主服务：用户级 `scmm-ui.service`，端口 5006。部署前核对 ExecStart、WorkingDirectory、MainPID、
  会话未保存修改及活跃任务，再按授权重启；只改代码无需 daemon-reload。
- 独立检验历史记录：端口 5007；`/home/crs/data/results/scmm-user-todo-preview`，项目在其 `projects/`，
  预设单独保存，两个合成项目及 `browser-result.json`/截图/下载证据。
  已记录地址为 `http://192.168.200.167:5007` 或 Tailscale `http://100.88.195.106:5007`；当前可达性需另验。
- 新的网页检验使用独立目录、空闲端口、`--isolated-storage`、`--project-root` 和独立 `SCMM_PREFERENCES`；
  不用真实实验项目做破坏性测试。具体启动命令见 [独立检验说明](docs/installation.md#独立端口检验)。
- `SCMM_UI_CONFIG`/`--config` 配置参数默认值；`SCMM_THERMO_READER`、`SCMM_DOTNET`、`SCMM_RAW_TIMEZONE`
  配置外部 reader/时区，具体依赖与路径见 [RAW 说明](docs/thermo-raw.md)。
  继承服务曾使用 WebSocket origin `*`，网络策略仍待确定，不把它写成已完成加固。

## 文档维护与接手

- 本文维护短上下文所需的当前状态、关键约定与导航；重要进展后更新日期、完成/验收边界和下一步。
  不复制全部会话、流水日志、完整待办或 API 参数表。
- 当前使用行为写入 [workflow](docs/workflow.md)，参数查 [parameters](docs/parameters.md)，
  数据格式查 [data-output](docs/data-output.md)，分析解释查 [analysis](docs/analysis.md)，
  环境/部署查 [installation](docs/installation.md)，排错查 [troubleshooting](docs/troubleshooting.md)。
- 未完成事项只在 [roadmap](docs/roadmap.md) 详细维护；提交、验证和部署证据记 [CHANGELOG](CHANGELOG.md)，
  机器报告保留在 `docs/validation/` 或明确的独立验收目录。详细架构与上游快照操作见 [development](docs/development.md)。
- 结束一轮工作时保留下一位代理能继续所需的信息：改了什么、哪些检查通过、用户验收到哪、
  是否部署、阻塞问题与下一步。历史编号文档可从整理前提交 `bc3e35d` 追溯。
