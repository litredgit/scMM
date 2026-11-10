# 12 开发与质量检查

[返回文档索引](README.md) · [安装说明](01-installation.md)

本页维护架构职责及跨模块契约。按[任务导航](README.md#按任务阅读)选择代码、必读主题和测试；
检查入口见[测试指南](13-testing.md)，服务操作见[安装与部署](01-installation.md#发布更新与回滚)。
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
下列树保留其他模块职责，使用流程以 [当前网页指南](02-workflow.md) 为准。

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

离子体系的内部基础位于 `ion/contracts.py`、`identity.py`、`semantics.py` 和
`application/data_views.py`：测量根隔离、精确内容身份、数值空间及独立分支目录。
`ion/species.py` 与 `relations.py` 提供数据库无关离子关系、条件天然同位素和逐样本证据；只输出候选/规则状态，不替代归组或人工接受。
`ion/hypotheses.py` 与 `representation.py` 负责带预算的角色解释、人工/探索资格和L1/L2；未知加合物包络使用独立质量坐标，不当作已知中性质量。
`ion/annotation.py`、`ion/evidence.py` 与 `application/compound_database.py` 提供本地通用候选、旧脂质排序适配及外部证据导入/作用域预览；不执行自动MS/MS匹配。
目录由离子页显式启用；启用后的提取/导入在保留旧分支基础上建立新测量来源。目录项目走版本2完整快照，正式保存与维护恢复分别处理报告与白名单模型，不降级为只保存活动矩阵。
`data_view_storage.py` 与 `project_references.py` 管理完整快照/引用闭包；`analysis_inputs.py` 统一来源、空间与敏感性报告。
`web_ions.py` 负责短锁事务与身份复核，`ion_jobs.py`/`ion_worker.py` 只为新增离子流程提供冻结输入、独立进程及校验后收集；状态与预算见[后台资源](01-installation.md#离子后台资源)。Vue 只持表单/摘要/分页，不持计算矩阵。

## 前后端能力覆盖

| 能力 | 网页入口与主要边界 |
|---|---|
| 原始谱、提取与预处理 | Vue 提供原始谱、SNR 预览、批次、人工审核、QC 和变换。legacy 提取保留给 Python、CLI 和旧产物兼容。 |
| 脂质与离子归组 | 脂质注释保留测量峰；离子页构建独立 L0/L1/L2 视图。Python 的旧去同位素可删峰或求和。 |
| 降维、聚类、统计、监督 | Vue 提供降维、聚类、差异、Marker、网络和模型诊断。分析模块的接入路径见下文。 |
| 时间分析 | Vue 提供 Palantir、窗口轨迹、代谢速度、趋势和趋势聚类。趋势聚类在请求内等待短进程。 |
| 数据管理 | Vue 提供显式子集、已处理矩阵合并、起点恢复、主动保存、QC/分析报告与矩阵 CSV。 |
| Python 工具 | 峰重建、秩一分解和部分绘图辅助由 Python 直接调用。入口的默认值和返回值以各自文档为准。 |

## 开发环境

日常修改在 `dev` worktree，`main` worktree 专用于生产；目录、服务与发布/回滚命令见
[开发与生产分离](01-installation.md#开发与生产分离)。5007 用于开发检验，5006 用于正式实验。

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
  原始文件打开、单扫描、分析与保存仍同步，剩余后台化见[待办清单](14-roadmap.md)。

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
优先级、环境变量和命令见[安装部署](01-installation.md#访问与路径配置)。

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


首次认证迁移使用 `release --migrate-auth`，前提及人工维护窗口证据见[安装部署](01-installation.md#监控初始化与生产只读检查)。
该路径仅支持旧版、不能覆盖新监控状态；测试覆盖非零/非法旧计数、新协议拒绝及安装/同步/健康失败后旧启动器和代码共同恢复。
常规发布继续使用新协议和时效检查。恢复备份位于仓库外；配置、认证库和监控库不随代码回滚。

### 维护与作图模块

`application/state_codec.py` 明确编码 AnnData/数组/表/图及受审核模型；`recovery.py` 原子发布并校验恢复包，
`maintenance.py` 管理页面握手和维护状态，`maintenance_runner.py` 在独立 systemd 任务中执行重启及配置回滚。
`deployment_maintenance.py` 管理部署通知、请求准入、正式写入保护及限时逐会话暂存/隔离恢复；超时线程只能留下未引用产物，不能迟到发布指针。
`deployment_client.py` 为本机维护建立及时撤销的审计管理员会话，串联通知、worker 身份核实/退出、暂存及报告；只读运维令牌不变。
部署默认允许临时状态损失；严格会话维护保留为可选入口。期限、容量及首次旧版升级边界见[安装部署](01-installation.md#发布更新与回滚)。
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

已计算结果与后续展示失败分别解释，不把后续绘图失败改写成计算回滚；重试展示不重算。下载在 blob 完成后再次检查操作/登录及工作区来源，丢弃过期输出。页面导航保留，冲突的修改/保存/计算仍串行；后端修订、候选原子性和保存冲突检查继续兜底。页面互斥只约束当前操作；计算取消按各入口的执行方式处理。

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

分析页原有模块注册、设置及执行组合函数继续管理分析事务，不为文件拆分重复创建控制器。脂质版本/筛选/审核和提取批次仍保留各自状态所有者。性能结论以实测为准。

## 模块状态所有权

| 模块 | 唯一管理职责 | 调用与失败边界 |
|---|---|---|
| `features/preprocess/useLipidPanel.ts` | 版本、匹配参数、筛选/分页、请求身份、人工审核与结果 | LipidPanel 每实例只创建一次；规则模块接收当前版本 getter 和刷新回调，不重复读配置或创建 store |
| `features/preprocess/useLipidRules.ts` | 规则草稿、预设、校验导入与规则分页 | 共享同一组 refs；来源重置由面板控制器更新，应用仍走原修订与版本检查 |
| `components/usePlotRenderer.ts` | Plotly 实例、渲染队列/代次、DOM 观察、激活清理、选择事件 | 接收面板已有 refs；导出通过 getter 使用已加载实例，不另建渲染控制器 |
| `components/PlotView.vue` | 展示/论文设置、图例次序、视口和导出生命周期 | 原 `useViewState` 只注册一次；结果身份检查和下载契约保持，预览 URL 由组件清理 |
| `application/time_inputs.py` | 输入/时间/数值检查、依赖展开及候选结果登记 | 接收候选 AnnData，不创建第二个工作区；现有应用事务负责验证后发布 |
| `application/time_analysis.py` | Palantir/窗口/速度编排及稳定兼容门面 | 保留原函数签名/导出，趋势适配器直接依赖 inputs，避免反向导入门面 |
| `application/time_outputs.py` | 经身份验证的表、metadata 与图 | 只读，不重新拟合；所有读取继续 require_run 和绘图输入身份校验 |

前端路径相对 `frontend/src/`；Python 路径相对 `scMM/`。局部回归入口见[测试职责](13-testing.md#场景隔离与失败归属)。

## 项目内产物管理与批次比较

`web_results.py` 的项目内管理只接受快照、完整预览缓存、独立导出或已识别批次的直接子路径；
调用工作区锁内检查未保存引用，其他工作区仍保护整个项目及其未保存导入来源，磁盘引用/任务/路径检查复用 `SavedItems`。
项目内计划和执行期间短暂固定全部工作区引用，繁忙工作区直接拒绝并提示稍后重试，不持锁等待。
计划与执行重新检查，并绑定工作区修订和项目；清理不修改项目矩阵或引用，恢复由统一回收站负责。
`batch_comparison.py` 只读冻结请求和已有逐样本产物，按稳定 ID/文件身份配对并验证可用摘要；
`web_raw.py` 负责工作区边界与图形呈现，Vue 只接收对比表、完整表导出和图形，不持有计算矩阵。

## 分析功能接入指南

本节是网页分析扩展的主要接入说明，示例全部来自已有四类分析，不增加演示算法。
先核对实际代码与分支；能力限制见[能力覆盖](#前后端能力覆盖)，科学解释见[分析说明](07-analysis.md)。
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
参数用简洁中文名，使用 `FieldLabel`/`HelpTip` 在悬停时提供英文键和中文说明。复用 `PlotView` 的图例、缩放和下载，
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

### 参数草稿与恢复

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
不要在未核对身份时应用迟到的成功或错误响应。`useReadScope` 同步递增本地输入/停用代次，
覆盖同修订内 A→B→A 的选择和 KeepAlive 恢复；恢复读取放在其回调内，避免嵌套组件的激活钩子顺序使合法读取被拒绝。
恢复回调只重新读取必要摘要，不重放写入。
结果图、搜索、摘要、原始参数/预设、提取信号及保存管理各自接收当前来源的响应；草稿另按发起读取时的编辑值复核。
`readResource` 仅合并同一登录/操作代次内并发的全局元数据 GET（项目列表、全局预设），结束即移除，返回各调用者独立副本；
它不缓存科学工作区响应，不跨写操作复用旧快照。`inspect` 的可选接收谓词仅用于只读信号/计划，过期成功与错误不发布；
正式变更及已发出的前台计算仍按原工作区事务完成，不因页面停用伪装取消。
`requires` 声明和 watcher 不代替后端有效性。
现有依赖并非通用 DAG；新增依赖要显式补齐保存、重载和失效处理，不能只改前端映射。
分析仍在同步 HTTP 内完成，锁不等于后台任务、取消计算或可断线恢复的任务协议；后台化见 roadmap。

### 按风险选择接入检查

- **算法/输入变化**：小型合成数值对照、边界/非有限值、缺可选依赖、seed 重现；真实实验另记，不能以浏览器成功代替。
- **状态/输出变化**：非法输入与计算失败保留旧状态、图失败保留新结果并可重试、输出键冲突、矩阵变更清理及无关元数据保留。
- **API 变化**：额外字段/非法操作拒绝、参数类型/范围、工作区修订冲突、越权身份与候选原子性。
- **前端流程变化**：四模块切换不计算、草稿与旧设置恢复、项目/数据切换重置；重复点击、报告/绘图等待期间互斥、旧成功/旧失败响应；宽屏与 700/390px，控制台无运行错误。
- **生命周期/存储变化**：主动保存后重载报告/图、模型只读限制、旧结果与图下载拒绝；完整 CSV/JSON/H5AD 精度，分页不影响导出；依赖字段和纯展示变化分别覆盖。
- **文档**：使用行为改 `02-workflow.md`，默认值/单位改 `04-parameters.md`，科学解释改 `07-analysis.md`，持久化改 `06-data-output.md`；本节保持唯一主指南，更新 CHANGELOG/roadmap 的验证与待验收状态。

现有定位：`tests/domain/test_analysis.py`、`test_analysis_views.py` 验证算法/图；
`tests/application/test_workbench_state.py` 验证生命周期；`tests/api/test_web_api.py`、`test_web_workflow.py`
覆盖严格契约、事务、保存重载/下载；`frontend/tests/analysis.spec.ts` 覆盖设置、导航、互斥、失败重试与迟到响应，
`workflow.spec.ts` 贯通四类分析、保存重载和完整导出。共享 store 改动还要选择导航/认证/其他读请求的受影响回归。
类型/构建为 `npm --prefix frontend run build`，文档链接/锚点为
`uv run --no-sync python -m pytest tests/tooling/test_documentation.py -q -W error`。
按[分块验证](13-testing.md#完整验证)选择受影响检查；仅改帮助文案或已有显示参数时，不机械重跑全部算法和真实实验。

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


## 新离子能力扩展契约

关系规则位于 `scMM/ion`，只能输出候选和可追溯证据；新增规则需覆盖跨化合物桥接、角色冲突、未知/缺测及资源触限反例。
来源、统计表示和化学身份分开：更新 L3 只追加目录证据，不能改变 X/层或偷偷重算表示。
新增定量策略必须声明响应假设、可用掩码及固定变量映射，不能把归组函数默认升级为离子求和。
多维度矩阵通过来源视图与分支组织，不将不同变量轴塞进同一 AnnData.layers。
局部 worker 只接受冻结 H5AD 与白名单参数，输出非可执行 JSON；新入口复核所有者、工作区/根/修订后最多收集一次。
worker 预算只用于运维配置。测试映射见 `api-ions`/`browser-ions` 和 ion-grouping 块。

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
