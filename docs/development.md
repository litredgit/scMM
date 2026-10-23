# 开发与质量检查

[返回文档索引](README.md) · [安装说明](installation.md)

本页维护架构职责及跨模块契约。按[任务导航](README.md#按任务阅读)选择代码、必读主题和测试；
检查入口见[测试指南](testing.md)，发布与上游来源见[发布指南](release.md)，新增能力见[功能接入](feature-development.md)。
默认只读根规则和任务相关主题，跨模块时沿调用和状态依赖追查；历史不作为每次任务的必读材料。

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
│   ├── retention.py       # 只读快照/缓存保留建议、引用与任务核实
│   ├── retention_cleanup.py # 显式策略清理计划、完整配对归档、身份复核及中断恢复
│   ├── retention_scheduler.py # 默认关闭的管理员持续规则、单线程周期、持久状态与停用
│   ├── project_batch.py   # 多样本持久 worker、重试及审核合并
│   ├── workbench.py       # 数据身份、预处理、分析与结果生命周期
│   ├── processed_merge.py # 既有质量匹配、分来源元数据/层及完整 union 起点候选
│   ├── merge_sources.py   # 安全装载、大小门限、内容身份及应用前复核
│   ├── merge_metadata.py  # 样本映射、无损类型及共同列
│   ├── merge_audit.py     # 完整预览/历史溯源 ZIP
│   ├── web_merge.py       # 所属工作区预览凭据、原子应用和历史下载
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
│   ├── _dataset_interop.py # 保存/转换门面、访问和注释
│   ├── _anndata_interop.py # AnnData 导入/导出与保留策略
│   ├── _dataset_candidates.py # 变换候选、轴校验与一次提交
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
| 基础预处理/QC | `analysis/quality.py`、`analysis/preprocessing.py`、`util/normalize.py`、`file/_dataset_processing.py` | 筛选、七种归一化、四种插补、异常检测高级参数、稳定 ID 子集和层/完整起点恢复 | PARAM-01 / SUBSET-01 / QC-01 已接入；各入口默认值分别保持，失败候选不提交 |
| 天然同位素 | 原 `CyESIData.deisotope()`、`file/_deisotope.py`；网页 `util/lipid_isotopes.py` | 网页按数据库分子式/加合物计算天然分布，保留所有峰，只标记、审阅与筛选导出 | ISO-01～03 与 ANN 联合；网页不使用旧 API 的删峰/求和及平方矩阵 |
| SDF 精确质量注释 | 原 `get_annotation()`；网页 `util/lipid_annotation.py` / `lipid_rules.py` | LMSD 本地准备、质量索引、完整候选、规则/预设、人工指定、独立版本及 CSV 已接入 | ANN-01～03；保留用户验收，背景任务迁移仍归 M2；Python/Notebook 旧默认值保持 |
| 细胞降维/聚类 | `analysis/embedding.py`、`analysis/clustering.py`、`PlotEngine`、`plot/embedding.py` | 五种降维、五种聚类、聚类参数白名单及着色已有；工作台保留候选提交，领域辅助函数负责参数校验/计算 | PARAM-03 已核对现有显式降维字段均有控件；三套 Python 入口的默认值/返回值不混用，Matplotlib 包装不重复造按钮 |
| 差异/Marker/相关网络 | `analysis/statistics.py`、`plot/_engine_statistics.py` | 检验、全局 FDR、筛选/分页、图形与导出已有 | 保持 STAT-01 解释和结果生命周期；不是待重新移植的功能 |
| 监督诊断/潜变量/SHAP | `analysis/supervised.py` | 分组验证、四模型、ROC/PR/校准、潜变量及 SHAP 已有 | PARAM-03 已接入 model_parameters.py 白名单/组合/训练折校验、四模型控件及 SHAP 显示设置；不序列化可执行模型 |
| Palantir 与窗口轨迹 | `PlotEngine.run_palantir()` / `compute_trajectory()` | `time_analysis` / `web_time`、严格 HTTP、Vue 命名结果、只读重载/全量导出 | 沿用现有定义，扩散核/多尺度近邻图断连检查仅网页显式启用；暂缓上游方法不引入 |
| 代谢速度 | `PlotEngine.metabolic_velocity()` | `time_analysis` / `web_time`、严格 HTTP、Vue 显式层/时间/单位、命名结果/完整表/只读重载 | TIME-02 已接入；沿递增时间计算强度斜率及范数，不能解释为示踪通量 |
| 代谢物趋势 | `plot_metabolite_trends()` | `time_trends` 适配既有数值算法、表/热图，`time_analysis` / `web_time` 管理命名结果与工作区；HTTP/Vue/完整导出/只读重载 | TIME-03 已接入；时间/层/精确 ID/名称来源/窗口统计可追溯，显示标准化不修改数据 |
| 趋势聚类 | `plot_trend_clusters()` | `time_trend_clusters` / 命名时间协议 / HTTP / Vue，完整分组/曲线/距离导出及只读重载 | TIME-04 已接入；复用原标准化/聚类，`plot/_trend_worker.py` 隔离拟合随机源/警告及诊断；短进程单并发/限时回收，非 M2 持久任务 |
| 特征距离嵌入 | `PlotEngine.feature_network()`；网页 `analysis/feature_embedding.py` | 独立特征距离 UMAP、层/ID/名称/类别、完整表及只读重载 | PLOT-02 已接入；Pearson 绝对相关/Euclidean 与相关阈值网络区分，常量/缺失及资源门限有明确规则 |
| 双特征散点/回归 | `PlotEngine.plot_feature_scatter()`；网页 `analysis/feature_scatter.py` | 独立面板、精确 ID/层/着色、全体细胞回归、完整导出及只读图重载 | PLOT-01 已接入；网页不采用 Notebook 的最近质量匹配，不将细胞级回归解释为生物重复验证 |
| 已处理结果合并 | `CyESIData.alignwith()`、`file.batch.concat()` | `merge_sources` / `processed_merge` / `web_merge` / 严格 HTTP / Vue，当前与完整起点独立候选、只读溯源 | MERGE-01 已接入；直接适配 H5AD/旧目录，复用原匹配规则；concat 仍仅读取旧目录，非批次校正 |
| 显式数据子集 | `AnalysisWorkspace.subset()` | 稳定细胞/特征 ID、数量预览、手动应用和完整起点恢复 | SUBSET-01 已接入；不是 `CyESIData.__getitem__` 的最近 m/z 强度读取，失败原子性及保存重开受检查 |
| 采集稳定性 QC | Notebook 稳定性段；网页 `analysis/stability.py` | 显式坐标/来源/参考特征、箱图/窗口数量/来源中位谱相关和完整表、只读图重载 | QC-01 已接入；存储顺序不当采集时间，不把细胞级 QC 当生物重复验证 |
| QC / 当前分析报告 | Python `analysis.quality.render_quality_report()`；网页 `analysis/quality_pdf.py`、`application/reporting.py` | 当前矩阵 QC PDF、分页分析摘要及完整数值/参数/图形附件 ZIP | REPORT-01 已接入；请求数据修订检查，不自动分析或保存项目，旧图身份不可核实则明确列为省略 |
| 峰重建与秩一分解 | `util.denoise.peak_recon()` / `r1_decomposition()` | 无应用/HTTP/Vue 工作流 | TOOL-01，工具级输入/科学定义/验证先于界面，不能替换现有提取算法 |
| 互操作/元数据/绘图辅助 | AnnData/H5AD、assign_source_metadata、EIC/质谱 Matplotlib、configure_plotting | Vue 已有保存重载、稳定样本元数据、Plotly 原始谱及导出 | 保留 Python 专用辅助接口，功能等价覆盖不要求逐函数建立控件；恢复原始输入和方法默认值分别管理 |

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
`deployment_maintenance.py` 管理部署通知、请求准入、正式写入保护及限时逐会话暂存/隔离恢复；超时线程只能留下未引用产物，不能迟到发布指针。
`deployment_client.py` 为本机维护建立及时撤销的审计管理员会话，串联通知、worker 身份核实/退出、暂存及报告；只读运维令牌不变。
部署默认允许临时状态损失；严格会话维护保留为可选入口。期限、容量及首次旧版升级边界见[安装部署](installation.md#发布更新与回滚)。
`maintenance_closure.py` 管理维护轮次内的一次性关闭审阅：只对经人工核实的失联记录及历史未登记请求更新证据，
不删除工作区，不授予只读运维令牌写权限；新活动、过期或审计失败不应用旧确认。
`api/routers/maintenance.py` 只开放认证管理入口。公开维护状态只含收集 nonce/完成标记，完整状态只给管理员。
`frontend/src/api/viewState.ts` 注册可恢复页面状态，`maintenance.ts` 收集已访问页面的参数/图及控件；密码、文件输入和账号配置不进入通用草稿采集。
`plot/export.py` 负责全精度 ZIP 与禁止外部资源/活动内容的 SVG→PDF；`plot/explanations.py` 和 `plot/isotopes.py` 提供可追溯解释图。

原始独立诊断由 `application/raw_diagnostics.py` 有界冻结扫描、`analysis/signal_diagnostics.py` 运行既有秩一/峰工具和构造完整对照图；HTTP 仅校验契约与前后输入身份，Vue 独立组件保存表单/图，不持矩阵或修改提取参数。


数据门面的归一化、插补、离群筛选、提取、对齐和去同位素先准备独立候选，由 `_dataset_candidates.py` 校验后一次替换实例状态。
需要调用用户函数/估计器的计算使用输入副本；失败不提前删除已有模板或更新部分帧。AnnData 转换策略由 `_anndata_interop.py` 管理，
目录发布仍由已验收的 `_dataset_persistence.py` 管理；不改变 CyESIData 的公开方法链或各入口默认算法。

`util/lifecycle.py` 提供与 HTTP 无关的序列化报告字段依赖/旧格式兼容判断，供应用结果目录和 CyESIData 元数据修改共同使用，
不反向导入应用层。结果目录保存全部已知结果的依赖证据，不依赖持久化模型或由数值推断标签来源。
结果目录同时集中关联图的父结果身份核对；每次新计算的身份独立于矩阵修订，维护恢复沿用工作台状态保存。
图的重新绑定须有原数据修订与结果身份证据，保存阶段先构造视图候选再原子发布；不能仅以图名推断有效。

### 前端轮询调度与页面代次

`frontend/src/api/polling.ts` 的 `serialPolling()` 仅调度只读状态：同一实例最多一个 Promise 在途，刷新请求共享在途 Promise，额外请求最多合并成一个后续轮次；定时器在实际完成后调度。`stop()` 清定时器并递增代次，`start()` 不能在旧请求未结束时另起请求，旧回调的 `isCurrent()` 永远不能因重新启用而恢复为真。停止不 abort 服务计算，也不伪造任务取消。

RawPage 在状态读取及开始收集前核对页面代次；`store.read()` 可传入只读接收条件，与工作区/修订检查同时约束成功和错误。ExtractionPage 停用后不更新局部批次、选中项或任务文案；侧栏仍可通过工作区共享读取更新全局批次。工作区心跳也串行，并绑定启动时工作区及代次，过期 workspace_missing 不能清空后来工作区。原始预览/提取已有任务服务和科学参数不变；操作结果区分、完整冲突矩阵和其他异步读取仍按 M1 后续范围审计。

### 操作返回值与完整互斥链

`frontend/src/api/operation.ts` 定义 `OperationOutcome`（succeeded/value、failed/error、skipped/busy、stale）、阶段及中文操作标签。`store.run()` 返回明确结果，void 成功也有 succeeded；忙时只返回 skipped，不改原操作的阶段或反馈。操作绑定递增代次及登录版本，`reset()` 使旧 scope 失效，旧 finally 不得释放新操作的保护；阶段更新只接受仍有效的 scope。反馈保存于前端，不进入科学项目格式。

兼容的 mutate/command/inspect 仍仅向既有调用方返回成功值或 undefined，并在装载响应前核对工作区、修订及操作 scope；内部操作不能仅凭 undefined 或全局 error 为空推断成功。`analysisTransaction()` 将接收结果、刷新和绘图放在同一保护内，绑定 API 的 read 支持 GET 及只读 POST，mutate 可显式 PUT；RawPage 的打开/参数应用/清除例外及提取审核使用完整链。需要将读取错误归属当前操作的步骤使用绑定 api.read，普通 store.read 是后台通道，只在其反馈代次仍当前、非繁忙且无既有错误时发布失败。

已计算结果与后续展示失败分别解释，不把后续绘图失败改写成计算回滚；重试展示不重算。下载在 blob 完成后再次检查操作/登录及工作区来源，丢弃过期输出。页面导航保留，冲突的修改/保存/计算仍串行；后端修订、候选原子性和保存冲突检查继续兜底。这是前端操作保护，不是 M2 的持久任务、后台取消或全局资源队列。

### 原始谱状态所有权与二进制导出

RawPage 保留原 DOM、参数键、视图键和展示入口，只组装 `features/raw/composables/useRawWorkbench.ts`。各模块持有自己的 refs，组合层通过明确动作连接，不复制状态，也不另注册请求/轮询：

| 模块 | 独立职责 |
|---|---|
| `useRawParameters` | 草稿/生效参数、预设、项目/样本来源切换与应用/清除链；统一注册配置读取 |
| `useRawSpectra` | 原始文件摘要、扫描导航、显示范围及 TIC/EIC/合谱/单扫描图；打开到初始图完成保持同一事务 |
| `useCellPreview` | 本地任务、编辑代次、状态轮询、接收结果和局部提示；来源重置清旧计数/提示，停止查询不伪造服务取消 |
| `useRawWorkbench` | 连接上述所有者，保持已有 `raw` 视图序列化字段及原 refs，提供页面绑定 |
| `api/workspaceDownload` | 共同二进制传输、网络/解码后登录与来源复核，以及 blob URL 释放；不解析或重编码数值 CSV |
| `preprocess/composables/useLipidImageExport` | 脂质图像的统一操作范围、冻结显示参数、SVG/PDF/PNG 与错误反馈；画布和临时 URL 在一个生命周期内 |

分析页原有模块注册、设置及执行组合函数继续管理分析事务，不为文件拆分重复创建控制器。脂质版本/筛选/审核和提取批次仍保留各自状态所有者；后续交互审计按 roadmap 收敛。模块化不作为速度或内存改善的证据，实际性能测量归 PERF-01。

## 本轮模块状态所有权

| 模块 | 唯一管理职责 | 调用与失败边界 |
|---|---|---|
| `features/preprocess/useLipidPanel.ts` | 版本、匹配参数、筛选/分页、请求身份、人工审核与结果 | LipidPanel 每实例只创建一次；规则模块接收当前版本 getter 和刷新回调，不重复读配置或创建 store |
| `features/preprocess/useLipidRules.ts` | 规则草稿、预设、校验导入与规则分页 | 共享同一组 refs；来源重置由面板控制器更新，应用仍走原修订与版本检查 |
| `components/usePlotRenderer.ts` | Plotly 实例、渲染队列/代次、DOM 观察、激活清理、选择事件 | 接收面板已有 refs；导出通过 getter 使用已加载实例，不另建渲染控制器 |
| `components/PlotView.vue` | 展示/论文设置、图例次序、视口和导出生命周期 | 原 `useViewState` 只注册一次；结果身份检查和下载契约保持，预览 URL 由组件清理 |
| `application/time_inputs.py` | 输入/时间/数值检查、依赖展开及候选结果登记 | 接收候选 AnnData，不创建第二个工作区；现有应用事务负责验证后发布 |
| `application/time_analysis.py` | Palantir/窗口/速度编排及稳定兼容门面 | 保留原函数签名/导出，趋势适配器直接依赖 inputs，避免反向导入门面 |
| `application/time_outputs.py` | 经身份验证的表、metadata 与图 | 只读，不重新拟合；所有读取继续 require_run 和绘图输入身份校验 |

前端路径相对 `frontend/src/`；Python 路径相对 `scMM/`。局部回归入口见[测试职责](testing.md#场景隔离与失败归属)。
