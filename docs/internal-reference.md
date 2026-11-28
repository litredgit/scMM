# 内部接口与数据契约

[文档导航](README.md)

下列入口用于维护网页的 Python 实现、任务产物和项目文件。正式用户操作统一通过服务器网页。先按对象定位所需约定，再查看实际调用与测试。

## 数据对象与文件契约

- [模块交换协议](#模块交换协议-v1)用于板块间数据移交。
- [项目保存与结果身份](#当前网页项目保存)描述磁盘与工作区的提交边界。
- [内部计算示例](#内部计算示例)按原始谱、矩阵和分析组织。
- [RAW 二进制协议](#流式读取与协议)用于核对 reader 与后端的读取行为。
- [内部参数及配置样例](#内部调用参数与排错)区分调用默认值和服务配置。

### 离子目录项目与源视图

L0–L3 与统计输入的关系见[离子定量视图](annotation.md#离子归组与化合物证据)。

普通项目仍沿用版本 1；显式建立离子目录后，主动保存使用版本 2。
两种结构均由当前网页写出，不是历史迁移链；当前版本不提供旧项目格式自动迁移。
网页入口见[离子归组与证据](annotation.md#离子归组与化合物证据)。

版本 2 的 `artifacts.data_catalog` 指向完整目录：测量根、L1/L2 源矩阵、逐分支的 current/baseline/views、
关系与证据注册表都有文件摘要和明确引用。写完全部候选并回读校验后才原子发布 `project.json`；
任一分支失败保留旧清单。活动分支继续提供兼容的 current/baseline/views 引用。
分支重开不重算，建立新的运行 token；正式项目只保存只读报告，维护恢复才沿既有白名单保留模型并逐分支验证。

完整项目包包含全部测量矩阵、分支、关系、定量和已托管的规范证据正文；原始谱只保留外部引用，不包含可执行模型。
导出包不触发项目保存。导入在隔离目录检查路径、重复项、容量、HDF5 外部链接及完整摘要，全部验证后才供安装。
单独的源 L2 H5AD 则只代表该源视图：保留 EC ID、定量映射、NaN 和布尔可测掩码；
缺原始测量根时明确记录缺失，不能冒充 L0 或重新归组。含结构性缺测的源不会直接进入只接受有限值的分析工作区，
需先明确选择共同可量化的细胞/变量后物化分析分支；测量未检出 0 不变成不可测值。

清理检查遍历全部分支、源矩阵和证据引用，活动工作区的非活动分支与未保存来源也受保护；
不能只根据活动矩阵或当前快照名称判断旧目录可删除。特征合并保持原接口；EC 合并必须显式对齐并声明响应可比性，
不同离子响应体系不靠同名或相同中性质量自动合并。

### 模块交换协议 v1

细胞提取、特征注释、统计分析均通过 `/workspace/exchange/{module}` 的独立导入、状态和导出边界交换数据，
`module` 分别为 `extraction`、`annotation`、`statistics`。导入须检查当前工作区修订，先构造并验证候选，成功后一次性替换；失败保留原数据。
完整包导入按清单替换当前全部数据来源、分支、处理起点和报告，保留目标项目身份。需要保留现有工作状态时先主动保存项目。
独立特征表导入建立仅特征的数据集合，原磁盘项目在主动保存前继续保留已存状态。

| 格式 | 内容与适用范围 |
|---|---|
| `.scmm-exchange.zip` | `manifest.json` 加现行项目快照，含当前数据、完整预处理起点、筛选恢复池、只读报告，以及离子目录的全部测量根、视图、分支、L3 候选/证据及人工审核；不包含可执行模型或原始谱文件 |
| 开放表格 ZIP | 当前矩阵、观测元数据、特征元数据及说明；表格不代替完整项目闭包，文本元数据不保证保留原始类型和缺失语义 |
| 独立 H5AD | 当前活动矩阵、同轴元数据/层及 `uns`，不包含其他来源视图、分析分支或完整预处理起点 |
| 特征 CSV | 稳定 `feature_id`、`mz` 及现有特征元数据，适合独立候选注释；不创建细胞或定量强度 |

完整包清单固定 `schema_version=1`、`kind=scmm_module_exchange`、`source_module`、创建时间和现行项目清单位置，
逐文件保存 SHA-256 和字节数，并声明观测单位、定量可用性、强度单位与数值状态、原始谱外部引用及模型排除。
导入拒绝未知协议、未声明/遗漏产物、摘要不符、越界路径、符号链接、重复或加密文件；
上传限 200 MB，解压及科学数组合计预算 2 GB，文件数量限 10,000。不把格式校验解释为来源或化学身份核实。

标准 CSV 每行一个观测、每列一个特征，首列为观测 ID；配套 `observations.csv` 使用 `observation_id`，
`features.csv` 使用 `feature_id`，按 ID 完整一一对应，不依赖表格行序。导入也可显式选择特征在行，
并支持 MetaboAnalyst 的 `Class`、`Group` 或 `Label` 分组列/行，保留分组原文。
稳定特征 ID 与显示名称分开；仅有名称的矩阵可以进行统计，但注释还需要有效 m/z，不能把名称猜作质量。
数值矩阵保留有限精度数值和真实零值，缺失/非数值/无限值明确拒绝，不自动填零或静默插补。
原始元数据类型、处理语义和完整来源需要使用完整交换包保留。

`observation_kind` 明确为 `cell` 或 `sample`。单细胞矩阵没有来源样本信息时，只记录统一外部数据来源，
不将每个细胞伪装成独立生物重复；样本行可按各自 ID 建立结果来源。来源列和生物重复仍需用户提供。
独立特征表以 `(0, n_features)` AnnData 保存，`uns.scmm_exchange_json` 明确
`feature_only=true`、`quantitation_available=false`，普通统计计算不能读取为定量矩阵。
图中无强度的标记只表示 m/z 位置，不是归一化峰高。不同 L0/L1/L2 变量轴继续使用独立矩阵，映射位于原生目录，不能塞入同轴 `layers`。

### `CyESIData` 数据模型

一个处理后的数据集由四部分组成。

#### `data`

pandas DataFrame，行是细胞事件，列是 m/z 特征，值是对应强度。

- 原始处理后未检出的峰通常记为 0。
- 列名可转换为浮点 m/z。
- 去同位素、填补和归一化会修改该矩阵。

#### `peak_meta`

与 `data` 行一一对应的细胞元数据。常见列：

| 列 | 含义 |
|---|---|
| `rt` | 原始文件内的保留/扫描时间 |
| `time` | 归一化到 0–1 的采集进程 |
| `label` | 来源文件名去掉扩展名后的标签 |

具体列还取决于 PyOpenMS 读取和帧对齐结果。删除异常细胞时 `peak_meta` 会同步过滤。

#### `feature_meta`

与 `data` 列一一对应的特征元数据。基础列为：

| 列 | 含义 |
|---|---|
| `mz` | 特征的数值 m/z |

运行去同位素后还可能包括：

- `deisotope_role`：`unique`、`parent` 或 `isotope`。
- `isotope_parent`、`isotope_order`。
- `isotope_slope_A`、`isotope_r_square`、`isotope_ppm_error`。
- `isotope_children` 和每阶 M+n 的详细字段。

内部注释结果还可能包括：

- `annotation_name`
- `annotation_formula`
- `annotation_adduct`
- `annotation_ppm_error`

#### `file_meta`

普通字典，保存数据集级元数据：

- `name`
- `ref_mz`
- `length`
- 仪器和采集时间，或多文件的 `per_file_meta`
- 去同位素处理参数和删除数量

正式分析建议额外保存参数、运行日志和 Git
提交 ID。

### 保存目录

```python
result_path = data.save("results")
```

假设 `data.get_name()` 为 `sample`，会产生：

```text
results/
└── sample/
    ├── .meta
    ├── data.pkl
    ├── data.csv
    ├── peak_meta.pkl
    ├── peak_meta.csv
    ├── feature_meta.pkl
    └── feature_meta.csv
```

| 文件 | 用途 |
|---|---|
| `.meta` | JSON 数据集元数据；也是 scMM 已处理目录的识别标志 |
| `data.pkl` | 高保真、快速重新加载的强度矩阵 |
| `data.csv` | 便于人工检查和跨软件交换的强度矩阵 |
| `peak_meta.pkl/.csv` | 细胞元数据 |
| `feature_meta.pkl/.csv` | 特征元数据 |

内部 worker 仅从受控产物目录读取当前 pickle 表；网页独立矩阵导入和模块交换见[选择交换格式](projects-and-data.md#选择交换格式)。CSV 往返可能把数值列名或可空数据类型转换成字符串。

`save()` 默认拒绝覆盖；显式 `overwrite=True` 时，先在结果根下的同文件系统临时目录
写完 JSON、pickle、CSV，并回读校验 pickle，再发布完整目录。覆盖保留用户附加文件，
不再保留新数据集未包含的 `feature_snr.pkl/.csv`；返回值仍是实际数据集目录。

同版本 scMM 的读取和保存共用结果目录旁的 `.scmm-dataset-<目录名摘要>.lock` 进程锁，
不要在读写期间删除锁文件。覆盖使用“旧目录移至同名摘要 `.backup` → 候选目录移至目标”的协议，
并非非空目录的单次原子替换：发布失败时回滚；若进程在两次重命名之间退出，下次读取或保存会恢复旧目录。
目标已存在而备份仍在时，表示新目录已发布；备份清理失败只记录警告，下次显式覆盖前重试清理。
恢复失败则报错，不能逐文件拼接两个版本。首次保存失败不发布半成品目录。

当前内部目录要求 data.pkl、peak_meta.pkl、feature_meta.pkl 完整；不再回退 CSV 或补造缺失元数据。只读介质无法创建锁文件时，读取前后检查目录身份，
发生替换时报错；需要恢复备份但无写权限时须先恢复写权限。进程强制退出可能留下
`.scmm-dataset-stage-*` 候选目录，它不会自动成为当前结果；确认无活动读写后再审阅清理，
不要将其中产物手动混入当前目录。外部逐文件读取、旧版 scMM、云盘同步与不支持本地锁/重命名语义的
文件系统不受该并发协议保护；本协议不保证断电后的落盘持久性，也不改变网页项目快照发布协议。

通过网页后台处理时，同一结果目录还会增加：

| 文件 | 用途 |
|---|---|
| `scmm-manifest.json` | 输入路径、完整处理参数、软件版本、质量提示和产物列表 |
| `quality-summary.json` | 细胞数、特征数、零值比例和中位质量指标 |
| `cell-quality.csv` | 每个细胞事件的总强度、检出特征数及可用采集元数据 |
| `feature-quality.csv` | 每个 m/z 的检出率、均值和非零中位强度 |
| `embedding.csv` | 固定种子的 PCA，以及依赖与数据规模允许时的 UMAP 坐标 |

这些文件不改变 `CyESIData.load_from_processed()` 所需的标准文件，可按需要与标准结果一起归档。

### AnnData 映射

`data.to_anndata()` 产生：

```text
AnnData
├── X      ← 细胞 × 特征强度
├── obs    ← peak_meta + source_index
├── var    ← feature_meta
├── raw    ← 首次转换的 X/var；导入模板时保留已有 raw
├── obsm
│   ├── X_pca
│   ├── X_umap
│   └── palantir_branch_probs
└── uns
    ├── X_pca_params
    ├── X_umap_params
    ├── trajectory
    ├── trajectory_metadata
    ├── metabolic_velocity
    └── metabolite_trends
```

首次从旧数据格式创建的 `adata.raw` 是当前转换矩阵的快照，不一定是原始仪器强度；先归一化再首次转换时 raw 同样反映已变换数据。
从 AnnData 导入往返时保留已有 raw，并按细胞轴裁剪；其特征轴可保留比当前 X 更多的测量特征，不用 raw 名称推断强度来源。

CyESIData 旧格式的 peak_meta 按行位置对应矩阵，索引可保留扫描标识；feature_meta 须按质量轴同序，feature_snr 的两轴须与矩阵一致。
导入的 AnnData 另要求稳定且唯一的细胞/特征 ID，并检查细胞索引对应；不按近似质量推断轴。
变换先构造并校验完整候选，失败保留数据、元数据、SNR 和分析模板。矩阵变换清除导入的嵌入/图和序列化只读报告，保留测量层和 raw；
重新提取/旧式对齐依既有策略丢弃 AnnData 模板，不能把它们当完整项目/层的合并接口。去同位素求和使 SNR 失效，注释审核不冒充已应用变换。
成功变换清除旧的内存去同位素审计对象；file_meta 的处理溯源继续保留，已有 length 字段随实际行数同步。
Python 离群筛选另记录传入种子（未指定为 null）或 NumPy RandomState 的拟合前状态及筛选数量；未指定种子不宣称可复现。

### 命名时间结果

网页 Palantir、窗口轨迹、窗口代谢速度、代谢物趋势及趋势聚类随当前 AnnData 保存，不保存可执行模型。
`uns["scmm_time_results_json"]` 为版本 1 的 JSON 注册表：每个命名结果保存 UUID、类型、生效参数、
实现/依赖版本、稳定细胞顺序、输入/输出摘要及观察字段依赖。Palantir 写入命名前缀的
`obs` 伪时间/熵、`obsm` 分支概率/多尺度坐标和 `uns` 分支名称/内部 ID 映射/参数；
窗口结果及每窗计数、权重和、时间中心、实际排序位置保存于命名 `uns` 及 `_metadata`、`_params`。
H5AD 容器转换采用规范摘要；请求中的 null/default 值完整保留在注册表 JSON，重开不重新拟合或重算。

科学输入、输出数值或稳定细胞顺序不匹配即拒绝读取/下载。矩阵变换清除时间结果；观察字段改动仅使相关结果
及其后继失效。失效输出只删除仍与旧摘要相同的本结果产物，不删除外部写入的替代值；失效键保留为占位，禁止直接覆盖。
时间图另绑定结果 UUID 和显示坐标摘要，换坐标或结果后旧图不能下载。计算/绘图不改变强度溯源。

完整结果 ZIP 包含 `metadata.json`，Palantir 为 `cells.csv`、`multiscale.csv`；窗口轨迹为 `windows.csv`、
`cells.csv`，包含全细胞 ID、原时间/全部坐标/分支概率与排序位置，以及全部窗口/分支数值。
速度结果的命名 `uns` 保存每窗特征均值、带符号斜率、范数、时间中心、有效计数、窗口起点及排序；
`_params` 和注册表记录输入层、时间含义/单位、递增方向及稳定特征 ID。特征 ID 变化也使速度结果失效。
速度 ZIP 为 `windows.csv`、`features.csv`（每窗口/特征一行，含稳定 ID、均值和斜率）、
`cells.csv`（原时间及排序位置）及 `metadata.json`，不受页面 200 行限制。
趋势结果的命名 `uns` 保存原始窗口池化值、有限细胞数、时间中心、排序、Spearman 的 rho/p/q 和排名；
`_params` 及注册表记录完整特征轴、所选稳定 ID、名称来源、时间含义/单位、输入层和窗口统计。
所选名称来源列、稳定特征轴或相关时间/强度变化后旧结果不可读取/下载；其他无关特征列不影响结果。
趋势 ZIP 为 `windows.csv`、`statistics.csv`（含稳定 ID/名称及 rho/p/q/排名）、`trends.csv`（每窗口/特征的原值及有限细胞数）、
`cells.csv` 和 `metadata.json`。保存的热图另记录显示特征 ID、前 N 项和标准化开关，不把显示标准化写回原趋势。
趋势聚类的命名 `uns` 保存标准化曲线、标签（无效 -1）、来源特征位置及完整所选距离矩阵；参数包含来源趋势键/UUID、
原时间/层/窗口参数、稳定 ID、请求/生效聚类参数、seed、依赖版本、实际簇数和距离回退/收敛诊断。
聚类同时复核来源结果 UUID、有效性和完整输入/输出摘要；不能以相同数组替换来源身份后沿用旧分组。
聚类 ZIP 为 `features.csv`（ID/名称/组/有效性/有测量窗口数）、`curves.csv`（原值/标准化值/有限计数）、
`distances.csv`（完整 source/target ID 和实际距离）、`windows.csv` 及 `metadata.json`。
拟合临时数值文件及任务诊断在仓库外私有临时目录生成，子进程成功/失败/超时后回收，不作为正式项目或可执行模型保存。
当前分析报告收录有效命名结果和元数据。空窗口保留空值，不将显示抽样或四舍五入写回源数据。
正式项目保存仍由用户主动执行；操作见[网页时间分析](statistics.md#时间与趋势)。

### 强度溯源

H5AD 的 `uns["scmm_intensity_provenance_json"]` 保存版本 1 的 JSON：`states` 按 `X` 与层名记录来源。
`raw` 表示明确记录的未归一化、未插补强度；`normalized` 表示仅经历 `total`/`max`/`pqn` 归一化；
`transformed` 表示插补、其他归一化变换或同位素强度求和；`unknown` 表示缺少可靠来源。
SNR 始终不作为强度。层的可用性由共享来源规则判断，不靠层名或非负值推断。

新原始谱提取显式记录 raw；Python 数据集在 `file_meta["intensity_state"]` 保留当前来源，
导出 H5AD 时同步 X 的来源；旧目录保存/读取也保留该字段。归一化、插补和合并传播来源，
不会将未知或已插补来源提升为 raw。纯 H5AD 往返保留各层已有来源，不修改其矩阵。

项目完整恢复起点自身携带来源；reset 恢复起点的矩阵、轴、层及其真实来源，
不会把导入时已经处理过的矩阵变回原始强度。restore 恢复所选层对应的来源。
独立 H5AD 导入的恢复起点就是导入矩阵，不等于文件中保留的原始输入层。

旧 H5AD、旧项目快照及历史缓存缺少显式来源时按未知兼容：允许导入、常规分析、保存与恢复，
但不会被提供为要求可靠强度来源的注释/网络层。旧历史可证明插补或变换，不能单独证明 raw；
无法靠 reset、层名或重保存补全来源。畸形或不支持版本的显式来源记录报错，不静默降级。
这些记录表达处理链来源，不能代替真实实验验收。

## 当前网页项目保存

三板块网页共用 `ProjectStore`，项目默认位于 `~/data/results`（可由 `--project-root` 指定），与 CLI/API 的标准结果目录不同。
`project.json` 记录样本、参数、修订号和当前产物引用；`description` 是项目备注，`created_at` 是新项目创建时固定的 UTC 时间，`saved_at` 只在成功保存项目时更新，缺失的创建时间不补造。`processing/` 保存批次请求、状态及日志，
`snapshots/` 保存发布所需的当前数据 H5AD、`baseline.h5ad` 和 `views.json`。
新项目目录使用 `项目名_YYYYMMDD-HHMMSS_短ID`，提取批次目录使用 `YYYYMMDD-HHMMSS_batch_短ID`，
快照目录使用 `YYYYMMDD-HHMMSS_r修订号_短ID`；名称中的时间为北京时间，清单时间戳仍保存 UTC。
当前数据与独立导出 H5AD 默认使用 `项目名_批次标签_YYYYMMDD-HHMMSS_r修订号.h5ad`；
未填写批次时省略，同名批次去重，多于两个批次时保留前两个并注明总数。
非法文件名字符替换为下划线，项目名和批次标签分别限制长度；短 ID 保证新目录彼此独立。
旧目录与固定 `current.h5ad` 继续按清单引用重载，不自动重命名。
独立导出默认保存在项目 `exports/`，允许修改新文件名，实际保存路径在网页显示；不会覆盖已有文件。
清单同时记录当前数据来源路径，供结果引用检查使用。

#### 操作与磁盘写入时机

“项目未保存”不等于服务器尚未产生文件：计算缓存、任务产物与正式项目快照分别管理。

| 操作 | 磁盘写入与恢复边界 |
|---|---|
| 新建项目 | 立即创建项目目录、初始 `project.json` 及 `processing/`、`snapshots/`、`exports/`、`analyses/`；没有矩阵时仅为配置项目 |
| 编辑样本、应用参数、审核建立数据、预处理或分析 | 先更新工作区；主动保存才发布正式项目状态。未应用表单为草稿，不成为生效参数 |
| 原始谱图 | 原始文件只读引用；图和本次读取结果留在工作区，不因此建立正式当前矩阵 |
| 细胞预览 | 写入下述任务、共同特征与预览缓存；缓存不等于审核纳入或正式项目保存 |
| 开始提取或重试 | **先调用完整项目保存，再启动新批次**；已有矩阵时也写新快照。预检失败不启动，保存后启动失败会明确报告配置已保存 |
| 批次执行 | 写 `processing/<批次>/request.json`、`state.json`、`worker.log`、逐样本 `<样本ID>.h5ad`。共同目标写 `shared_features.npy` 与 `spectrum.npz`，独立寻峰写逐样本 `<样本ID>-spectrum.npz`。检测记录写 `<样本ID>-detection/traces.csv` 与 `detection.json` |
| 保存项目 | 有矩阵时先写当前 H5AD、完整 `baseline.h5ad` 和 `views.json`，再原子发布 `project.json`；无矩阵时保存配置及已有视图。旧快照继续保留 |
| 独立服务器导出 | 默认写 `exports/`，也可选择已配置的允许位置；不覆盖，不更新项目清单，不包含独立完整起点 |
| 浏览器下载 | 图像、CSV、报告下载到用户电脑，不自动在项目目录留副本，不保存项目；上次快照 H5AD 下载只读取已有文件 |

图和报告可只读重载，正式快照不保存可执行训练模型。`analyses/` 不是当前网页每次分析的自动落盘位置。
主体插件的统计表、图和运行溯源保存在活动数据的 `uns.scmm_method_reports_json` 中，使用协议版本 1。
读取、完整 CSV 和图形导出按记录的输入轴、层与观测列检查有效性。[主体方法协议](method-plugins.md#矩阵与报告)
任务启动/停止还使用 `start.ready` / `stop.requested` 控制文件；临时计算文件及维护恢复包不属于正式项目快照。

细胞预览的冻结请求与阶段状态位于 `processing/preview-jobs/<任务 ID>/request.json`、`state.json`，
预览产物仍使用 `processing/preview-<ID>/`，沿用输入身份、参数、共同特征及产物完整性校验。
预览任务不会列入提取批次，也不直接发布 `project.json`；只有当前会话接收有效结果并主动保存后，
清单才包含对应预览引用。阶段状态保留诊断与发布前活跃任务检查，不提供预览会话恢复。

新提取批次冻结输入文件身份，在执行前、共同特征构建后及逐样本提取前后检查；成功 H5AD 与共同特征轴保存 SHA-256 摘要。
重试只复用身份、参数及摘要一致的成功产物。旧批次可继续查看和审核，缺少冻结身份时须新建批次，不能直接重试复用。
`views.json` 兼容既有 Panel 图形 JSON 字符串和 Vue 图形对象；Vue 分组分析设置及逐图图例也保存于视图数据。
Vue 逐图视图还保存导出范围（默认当前视图/可选完整范围）、坐标视口和图例显隐；
系统自动图文使用英文，用户输入的名称与自定义图文保留原文。
图例位置保存在 `legend_positions`，分类顺序保存在 `legend_orders`（图键到类别名称列表）；未设置或新增类别默认自然升序。
尚未建立矩阵的原始谱项目也会先写视图快照，再将 `artifacts.views` 原子发布到清单；此时不存在 `current`/`baseline`，重开只恢复视图。
批次状态增加 `stage`、`stage_progress`、当前样本及开始/更新/结束时间；样本可保存阶段与进度，旧批次无这些字段仍可查看和审核。
图表表格显示可采用科学计数法，CSV 下载保留后端原始数值精度；分页展示不截断完整下载。

点击“保存项目”先写完整快照再发布清单，跨会话保存检查修订冲突。重载恢复当前数据和完整
预处理起点，图和报告为只读记录，不恢复可执行模型；数值矩阵只提供一个当前版本，不提供历史分支。
监督只读诊断新增 `validation_audit`，保留按类别及每折的细胞/来源组计数、输入层、强度来源、
记录级预处理提示和解释边界；与监督 JSON 下载一致。旧报告无该字段时仍可读取，不补造历史或来源计数。
新聚类步骤的历史参数含 `effective_parameters`，记录所用算法实际生效的白名单参数；
旧步骤缺少该字段时不补造，标签照常读取，项目设置中的新字段使用各自兼容默认值。
显式子集同步裁剪/重排当前 X、obs、var 和全部 layers，清除过期嵌入/分析；保留稳定 ID、强度来源及历史中的精确所选 ID。
完整预处理起点不被子集替换，保存重开后 reset 仍恢复原始完整轴；单层 restore 只恢复当前子集轴上的历史强度。
新增归一化、插补和异常检测步骤在历史 `parameters.effective_parameters` 中记录方法实际使用的白名单配置，随快照/H5AD 保留。
当前报告为按请求生成的只读产物，不自动写入项目清单。QC PDF 绑定当前数据 ID/修订、X、来源及未保存状态；
报告 ZIP 含 `report.pdf`、`metadata.json`、`history.json`、`cell_qc.csv`、`source_qc.csv`、`results.json`、
已有完整 `results/*.csv`、`embeddings/*.csv` 和身份匹配 `figures/*.json`/作图 CSV。文件名使用安全序号，原嵌入键/图名/表名在 metadata 映射中保留；
图 JSON 的完整 export_tables 拆成单独 CSV，矩阵/历史/数值不按 PDF 显示精度舍入，JSON 未定义统计值写 null。
原 obs 已有 cell_id 时另名保留，导出 cell_id 为权威稳定观测 ID。PDF 不是完整项目/模型备份，也不纳入自动保留/回收。
省略的旧图及其身份原因列入 metadata；旧只读报告没有保留的中间值不补造。边界见[报告解释](statistics.md#统计解释与网页分析)。
采集稳定性 QC 存于 `views.figures.stability`，分析草稿为 `stability`；完整 `cells.csv`/`windows.csv`/`profiles.csv`/`correlation.csv` 及时间含义/来源/层/参考特征随只读图保存，非有限/未定义项保留缺失标记。
特征距离嵌入存于 `views.figures.feature_embedding`，草稿在分析设置 `featureEmbedding`；元数据保留输入/有效参数及完整 `features.csv`/`distances.csv`，矩阵变换使其失效，重开后可读取/下载只读图，无需重算 UMAP。
双特征散点存于 `views.figures.feature_scatter`，输入草稿存于分析设置的 `scatter`。
图元数据保留精确特征 ID、层、着色列、回归定义/系数及解释；作图 ZIP 的 `cells.csv` 保留全部细胞和 `included`，
`regression.csv` 保留完整回归结果，不按屏幕显示精度舍入。重载后绑定当前工作区身份供下载，不恢复任何可执行模型。
脂质注释版本只切换候选/标记等元数据，矩阵轴和强度保持相同，见[注释版本](#脂质注释版本与导出)。
快照尚不自动清理，重复保存会增加占用。Vue 结果浏览按用途显示所属项目、时间、大小和保护说明：

| 用途 | 保留原因与管理方式 |
|---|---|
| 当前快照 | 上次保存的当前矩阵，由 `project.json` 引用，禁止单独删除 |
| 恢复起点 | 完整预处理起点，支持找回筛除前的轴，禁止单独删除 |
| 历史快照 | 以前的保存产物，默认保留；无引用且无活动会话/任务时可按删除计划移入回收区 |
| 逐样本提取 / 批次 | 成功样本 H5AD 用于审核、复用、重试与溯源，不等于已建立的当前矩阵 |
| 预览缓存 / 任务 | 细胞预览可能写入 `data.h5ad`，供参数一致时复用；不直接纳入当前数据 |
| 独立导出 H5AD | 主动导出产生的单独矩阵，保留当前轴上的层、嵌入和只读报告，不包含完整项目恢复起点 |
| 外部或独立 H5AD | 按文件识别，来源和处理状态须核对内容；删除前同样检查引用 |

预览复用同时检查原始文件真实路径、大小、纳秒修改/状态变更时间与 inode、完整处理参数，
以及 H5AD、共同特征数组、检测曲线和细胞窗口元数据的 SHA256；共同特征模式还须与当前目标数组完全一致。
校验结束再次检查输入身份；预览写入期间输入变化时不发布有效缓存清单。
缺少完整校验清单的旧预览或缺失/损坏的产物视为未命中，重新计算，不影响已保存项目矩阵。
共同特征缓存按全部输入身份及共同特征参数索引，并检查数组摘要及读取前后的输入身份。
重新定位原始文件会清除该样本预览关联；即使复制内容相同，也须在新路径重新计算后才能复用。
这里的原始输入身份是文件系统元数据检查，并非原始谱全文哈希或跨存储内容寻址；不承诺检测可伪造全部元数据的外部改写。
缓存失败遗留目录不自动删除，仍按可审阅清理计划处理。

保留计划的操作与筛选条件见[快照与缓存管理](projects-and-data.md#快照与缓存管理)。实现枚举本环境项目的快照、完整预览和共同特征缓存，后者按 .npy/.json 配对。当前清单、完整起点、视图、预览关联及其他已配置项目的来源引用均受保护。引用或任务状态无法核实、符号链接及检查期间状态变化时保留对应产物。JSON 区分无引用候选大小（candidate_bytes）与规则建议大小（selected_bytes），默认建议大小为 0。两者均为逻辑大小。

“查看策略清理执行计划”单独冻结策略选中的完整清单与文件身份，产生绑定当前用户工作区的执行令牌；
只读建议及其他工作区的令牌不能执行。点击“将策略清单移入回收区”后消费令牌，
按显式年龄/数量规则批量处理已审阅清单，不扩大到生成计划后新增或刚达到年龄的项目；变化时要求重新查看计划。
一次性清单由用户直接触发；持续策略须由管理员另外审阅启用，不能用该清单令牌开启。

策略清理只处理本环境项目中可核实、无引用、无活动工作区/任务的历史快照、完整预览与共同特征缓存文件对。
执行持项目/结果根/回收区存储锁，服务内预留目标项目，阻止打开与清理/恢复互相穿越；
长时间复制不持工作区管理器锁。先为全部成员建立完整恢复副本，按相对路径与 SHA256 校验并刷盘，
复制结束再次核对来源身份、引用及策略清单，再逐项移走原件；需要额外可用空间，磁盘不足不会提前删除原件。
归档为一个回收条目，`record.json` 的 `retention_version: 1` 记录原项目、逐项路径、摘要及策略，
`payload/<序号>` 对应成员；共同特征 `.npy/.json` 一起归档、恢复。新归档还记录稳定项目 ID，
原路径已替换为另一项目时拒绝恢复；早期无该字段记录按既有路径恢复边界处理，不能补称已验证项目 ID。
既有单项目/结果回收格式继续兼容。
原始谱、未识别产物、任务/批次诊断、当前快照与完整起点均不可用此入口清理。

普通移走失败会尝试从完整副本恢复已移走或部分删除的成员；进程中断或自动恢复失败时，
回收区显示 `prepared` / `restoring` 的未完成条目，完整归档保留，须先恢复才能永久清空。
恢复先验证全部归档及原路径，允许匹配原件或部分删除目录中仍匹配的幸存内容，拒绝同名不同内容和越界/符号链接；
补齐缺失内容后重新校验，不覆盖用户新写入的内容。恢复过程中失败可重试，归档保留。
恢复内容已完整校验而残余归档删除失败时记为 `restored`，可再次恢复以完成收尾，或由管理员永久清空残余归档。
移入回收区不释放磁盘空间；永久清空仍为独立管理员动作，须通过已有引用/活动保护。
只读计划仅检查当前服务的工作区及已配置结果根，其他服务/未配置目录中的未保存引用不能据此判为空闲。

### 脂质注释版本与导出

与目录测量根关联的候选覆盖保存在目录证据注册表，绑定测量根身份。普通项目沿用当前数据的注释存储。
各次 MS/MS 比对记录保存参数、来源摘要、完整谱表与阈值结果。关联及撤回保存目标、版本、样本池与审阅历史。
项目文件比对另保存原文件 SHA-256、扫描索引范围、原生扫描号及前体采集元数据。原始谱重叠复核记为
`ms1_overlap`，绑定测量来源、注释版本、两个候选 ID 和原始文件身份。局部连续谱及两个模型的预测保存在
`profile_review`，无法拟合时保存诊断。证据关联校验测量来源和候选身份。
普通项目将记录存入视图快照，目录项目记入证据注册表，两者都随完整交换包转移。独立矩阵和纯特征 CSV 只携带对应列和数值。

`AnnData.uns["scmm_lipid_annotations_json"]` 保存 schema 1 的 JSON，包含 `active` 版本 ID 及 `versions`。
每个注释版本保存时间、名称、数据库文件摘要/来源、参数、评分规则、完整候选、逐样本同位素关系、
人工指定及核对进度、分布算法版本和不能计算的候选诊断。候选和关系使用稳定 ID，重复 m/z 的不同 feature ID 分开处理。
`var` 的 `lipid_candidate_ids`、`lipid_isotope_match`、`lipid_annotation_version` 是当前版本的索引/标记，
完整物质名称逐条保存在候选和关系表中；不使用 `/` 合并候选名称，不覆盖用户原有名称字段。

版本输入身份包含特征 ID/mz、细胞 ID、样本分组和选定强度层的完整 float64 内容。
保存重载不依赖内存工作区 ID、当前数据库可用性或可执行模型。矩阵变换后元数据仍可携带历史证据，
页面验证来源身份后才允许作为当前结果审阅/下载，不能把已过期的 var 标记当作有效当前结论。
不变原始输入层上的普通归一化不使注释失效；细胞/特征裁剪、分组或该强度层改变使版本过期。

新增版本的 `network` 保存独立 schema 版本、相关参数、两种输入层/内容身份、明确的条件映射与样本范围，
`feature_edges`/`molecule_edges` 保存达到绘图阈值的特征对及所有化学关系对的逐样本全细胞/共同检出相关、
共同检出数/比例、可评估状态和原因；不保存无展示/无化学依据的阈下成对数组。
`chemical_links` 保存来源候选、关系类型、理论质量差或同位素关系 ID、逐样本化学/相关支持、共识及方向冲突。
`representative_metrics`、`representatives` 分别保存项目各样本等权指标与人工代表；`view`/`chart_filters` 保存显示设定。
图表以这些只读数据和设定重建，SVG/PNG 由页面导出，不向实测矩阵写入合并值。
候选人工选择变化后更新映射及支持，计算参数变化生成新版本；条件字段或任一相关输入层内容变化后拒绝旧版图表/证据下载。
未改变依赖字段的元数据修改不使版本失效；原始层不变且分子网络为派生 `total` 时，当前 `X` 普通归一化不改变输入身份。
旧版本未含 `network` 时仍可查看原注释与饼图，运行新版本才能获取网络。
图表 JSON/节点和边 CSV 注明方法、层、范围、参数和注释版本；嵌套逐样本证据在 CSV 内以 JSON 保存，保留完整精度。

独立导出 H5AD 含当前矩阵及这些注释版本，但仍不含项目完整恢复起点。
筛选矩阵 CSV 仅按稳定特征 ID 裁选当前矩阵列，细胞不裁剪、不重复，不按当前分页或核对的单个特征截断。
候选 CSV 按一对多候选逐行保留名称、分子式、数据库 ID、极性/加合物、质量误差、原规则分、网络等级及支持样本/关系；
完整同位素 CSV 另保存母/子 ID、来源候选、样本、阶数、理论/实测比例和人工状态。
筛选不修改 `X`、layers、SNR 或恢复起点，也不影响已有数值模型。

### 回收与恢复记录

网页删除统一移动到开发/生产共享的 `~/data/results/recycle/<北京时间_短ID>/payload`，不读取或迁移旧回收条目。
`record.json` 记录原路径、类型、删除时间及预览身份。执行前重新核对文件树身份，并在项目锁下检查
清单、H5AD 溯源、活动网页会话及未结束任务；引用检查覆盖已配置存储中的可识别项目。
项目整体删除包含自身快照及任务产物，不移动清单引用的外部原始谱。
恢复保留原目录名和文件内容，须位于当前开放存储，拒绝覆盖、越界、符号链接及缺失父目录。
跨文件系统移动先复制并校验内容，再发布目标及删除源；复制失败保留原内容。回收操作共用目录锁。
移入回收区不释放磁盘空间；网页“清空回收区”直接永久删除全部共享条目，不二次确认。
清空前核对完整清单、引用、活动任务及符号链接；部分失败报告已清理数量和剩余条目。
其他进程或未配置存储中的引用无法全部发现，回收区也不替代备份或自动保留策略。

提取细胞元数据增加峰顶/窗口起止扫描索引、保留时间、扫描数和源文件身份；原始文件改变后不可重用旧索引。
作图 ZIP 保存完整数值精度，图形的显示格式不改变源表。数据库完整元数据保留无效质量行并标识有效性，匹配只读取有效正质量记录。

原始信号独立诊断以项目视图保存最近成功诊断的参数与只读图，不向 AnnData 写入层、嵌入或提取结果。
图内 `diagnostic.csv` 含全部扫描/通道的原始信号、基线、扣基线信号、峰、重构、残差和秩一对照；
`noise.csv` 区分迭代估计 sigma、残差总体标准差和秩一残差 RMSE。
参数和原始输入身份随图保留；这些附件不是可执行模型，不替代原始文件或提取审核。

网页原始图的 input_identity 中，文件大小、纳秒时间戳和 inode 以十进制字符串传输，避免浏览器整数精度损失；下载仍按当前文件全部身份字段逐项核对。内部文件身份和缓存计算继续使用原整数，不改变缓存键语义。


#### 统计与监督报告目录

现有 differential、markers、network、supervised、shap 共用应用层显式结果目录管理保存/读取与关联图失效。
正式快照保存表格记录及列顺序（含空表），监督只保留诊断、类别/细胞标识及训练参数，不保存可执行模型。
新网络报告还保留完整相关矩阵与孤立节点，重载后可重新构造只读网络图，并将完整相关表纳入报告 ZIP。
旧网络报告若没有相关矩阵则保持缺失，不从边表补算；已有节点/边仍可用于只读图。
新报告均以 `_observation_dependencies` 记录其观察字段依赖；SHAP 记录监督标签/来源字段依赖；有完整父模型报告的旧 SHAP 继承父报告依赖，无关批次编辑保留结果。
缺失依赖证据的旧监督/SHAP 报告在元数据改变后继续保守失效。重新训练清除全部四类 SHAP 图及解释，失败仍保留原结果。


Python `assign_source_metadata(..., overwrite=True)` 使用同一只读报告失效规则：修改目标分组会删除依赖它的报告及其 SHAP 后继，
无关批次字段或同值写回保留有效报告。新分组值可加入已有分类字段；不改变矩阵、测量层/raw、稳定 ID 或纯矩阵嵌入。
依赖字段、JSON 或报告版本异常时，在候选提交前报错，当前元数据与报告均保留；不猜测未来格式。


监督潜变量以 `latent_dependencies_json` 记录标签/来源列依赖；修改相关列时同时移除坐标和其 split 列，
纯矩阵 PCA 等嵌入保留。旧潜变量缺失依赖时保守失效；同名键随后由普通降维生成时，以最新写入者为准。
当前数据和完整恢复起点分别计算字段变化：只修改已排除来源的起点元数据，不使当前数据报告失效。

每次结果计算生成独立 `_result_identity`，关联图同时绑定结果身份和数据身份；同一矩阵重新训练也使旧图失效。
保存/重开保留该身份，只在来源证据匹配时重新绑定会话内数据身份。旧图缺失结果证据时需重新生成。
维护暂存保留结果身份；正式项目仍不保存可执行模型。只读监督混淆矩阵可用保存的计数重新绘制，
ROC/PR/校准图只复用身份匹配的已存图，不重新训练模型。

### 合并矩阵与完整起点

合并当前矩阵按明确的 union/ref 规则构造；完整预处理起点独立以 union 合并各输入实际起点。当前工作区使用完整 `_original`，独立 H5AD使用自身装载的数据。两者分别验证、一次性替换，失败不污染工作区，不写入源文件或正式项目；主动保存沿用快照原子发布与磁盘修订检查。

细胞/特征稳定 ID 加 `mN:` 来源前缀；目标 sample_id 由本轮合并身份及目标样本名生成。原 obs/var 列按 `mN__` 保留类型和精度，原始表与 uns 归档在 `uns['scmm_merge_sources']`。只有显式声明的共同 obs 列形成共同字段，group/subject/batch 默认保留逐细胞原值，可在映射中覆盖；同名目标样本主动合并，异质样本字段不会被静默统一。

X 缺少目标特征补 0。每个输入层独立存为 `merge_mN_layer_K`：自身细胞缺少特征补 0，其他来源细胞为 NaN；不把不同输入的同名层当作同一科学量。raw 保留各来源独立命名的原始特征轴和注释，不作质量对齐；其他来源细胞为 NaN。层来源表说明原键与新键。原 obsm/obsp/模型不进入活动结果，原分析 slot 名归档供审计；输入的强度状态按保守规则记录，不自动重做归一化。

`uns['scmm_merge_json']` 保存 schema_version=1、合并 ID、来源文件 SHA256/当前和起点身份、参数与顺序、完整质量/样本映射、各角色的尺寸和实际 mode。当前和起点分别记录，起点固定 union。历史溯源 ZIP 和报告中的 `historical_merge_mapping` 明确标为 `historical_merge_not_current_analysis`；后续筛选/归一化仍可读取当时映射，不冒充仍有效的当前分析。项目保存重开、H5AD 往返保留这些只读数据，不保存可执行模型。

### 保存与恢复的回归依据

覆盖旧目录时，曾在写 `peak_meta.pkl` 注入 OSError 后读到新矩阵与旧分组；
因此逐文件 replace 不足以证明整个数据集原子发布，需验证关键写入点失败、并发覆盖、
可选 SNR 清理与不完整产物拒绝。协议见[保存目录](#保存目录)，检查见
[数据互操作](../tests/domain/test_h5ad_interop.py)与[处理任务](../tests/application/test_processing_tasks.py)。

插补后导出 H5AD 再导入/reset，曾把不变的已插补 X 误判为原始强度；普通项目有独立 baseline，
不能扩大为所有 reset 错误。恢复须携带真实来源，未知来源不能按非负值或层名猜测。
矩阵 normalize 后曾保留旧 `X_pca`/参数；因此变换须统一处理已知下游结果，纯往返继续保留模板信息，
不能删除整个导入模板绕过依赖判断。任意外部 uns 的依赖不可自动推断。


当前项目缺少 `cell_min_signal` 时明确拒绝打开，不再自动补为 0。已有磁盘数据不批量改写或删除。


### 筛选恢复池与外部证据

可逆标签的完整筛选前数据作为独立 `selection.h5ad` 保存，不占用不同特征轴的 AnnData layer，也不替代 `baseline.h5ad` 的预处理重置语义。普通目录项目清单与离子目录分支分别引用该文件，沿用原子发布、校验和引用闭包检查；恢复时核对标签、轴和当前矩阵数值。内存中启用标签需要额外保留一份完整矩阵，关闭全部标签后释放恢复池。

独立 H5AD 导出仍是当前矩阵；若只有筛选后矩阵而没有完整恢复池，拒绝以关闭标签的方式假装恢复缺失项。完整恢复需打开原目录项目。标签变化使下游分析与已有图失效，关闭标签不会自动恢复旧模型或结果。

相关性、集合和 MS/MS 图沿用只读图保存机制，在图的 `export_tables` 中保留完整表。图旁「作图数据导出」可预览并下载这些数值。候选集合另存候选到特征及数据库版本的映射。外部注释将字段写入当前特征元数据，并同步重置起点中共有的稳定特征。导入记录保留来源 SHA-256、字段映射及匹配口径。

MS/MS 图保存实测/参考谱、来源 SHA-256、逐扫描候选、匹配碎片、阈值和样本池范围。当前功能不自动覆盖候选身份、人工鉴定等级或离子目录的外部断言；池化证据不会自动变为每个细胞的结构鉴定。

#### 数据编辑记录

数据编辑器通过样本元数据接口及按稳定特征 ID 匹配的注释接口更新名称与元数据。定量矩阵预览只读。样本修改记录保存在 `uns["scmm_metadata_edits_json"]`，包含修改时间、工作区、样本 ID 及修改前后的名称、分组、个体与批次。特征显示名称沿用 `uns["scmm_manual_annotations_json"]`，记录时间、工作区、用户、来源、匹配与实际修改项，并同步恢复起点；稳定特征 ID 和科学字段继续受保护。元数据与显示名按现有同步规则更新恢复起点，筛选标签使用既有纳入范围机制。

## 流式读取与协议

```python
from scMM.file.readers import ThermoRawReader

with ThermoRawReader("sample.RAW") as reader:
    for spectrum in reader:
        mz, intensity = spectrum.get_peaks()
        # 逐扫描消费，不用 list(reader) 缓存整份原始谱。
```

reader 是单次上下文；数组为只读 bytes 视图，退出后仍有效，修改前需复制。
`SCMMRAW1` 协议如下：

所有整数与 float64 均为小端，无结构体 padding；文本为 int32 字节长度 + UTF-8。

- 文件头：8 字节 magic、int32 扫描数、采集时间文本（不虚构时区）、仪器文本。
- scan：uint8=1、int32 原始编号、int32 MS level、uint8=1（profile）、
  float64 RT 秒、int32 点数、float64[点数] m/z、float64[点数] intensity。
- 结束：uint8=0、int32 实际扫描数、int64 总点数；随后 EOF 和进程退出码 0。
- stderr 仅诊断；stdout 不允许日志。缺失结束标志不算成功。
- 不排序、去重、补零、裁剪或滤波；空 profile scan 保留。

### 采集信息读取

helper 的 `--header file.raw` 逐扫描检查 profile 状态，输出含 `schema_version=1`、
`scan_count`、`creation_time` 和 `instrument` 的 JSON。它不读取完整 profile 点数组。
Python 校验协议版本后按输入和 reader 文件身份缓存采集元数据，完整谱流仍校验实际扫描数及结束标志。

helper 的 `--acquisition file.raw` 模式只读取前 32 个 MS1 扫描的采集质量窗和分辨率附加记录，输出版本 1 JSON，不传输 profile 数组。质量窗来自扫描设置，分辨率仅接受明确的 FT Resolution / Orbitrap Resolution / Resolution 字段，排除带 ppm 的分辨率补偿值。缺失字段保留缺失，参考质量未知时不自动应用到 m/z 200 参数；超时、退出失败和无效 JSON 明确报错，不回退为固定提示。

Python 与 helper 必须同步更新。开发服务使用独立 reader 发布目录，验证后发布时再同步生产所配置的 reader；不要用开发构建覆盖运行中的生产依赖。

## 内部计算示例

### 单个原始文件

```python
from scMM.file.data import CyESIData

data = CyESIData.load_from_file(
    "data/sample.mzML",
    ref_mz=734.5929,
    ppm_tol=10,
    resolution=35_000,
    resample_points_per_fwhm=5,
    ms_peak_snr_threshold=10,
    cell_snr=5,
    cell_min_signal=1e5,
    baseline_filter_size=50,
    max_zero_frac=0.9,
)
```

`load_from_file()` 完成谱读取、总谱构建、去噪、公共峰提取、扫描对齐和细胞事件识别。
返回的对象可以通过 `len(data)` 查看细胞数，通过 `data.data.shape` 查看完整矩阵形状。
`cell_min_signal` 在 `preprocess`、单文件及各目录入口均可调，默认 `1e5`。
逐扫描参考离子必须同时通过原倍数条件和扣基线后的最低净信号条件；0 关闭附加条件。
定义和单位见[参数说明](extraction.md#每次扫描须同时满足两个条件)。

#### Thermo profile RAW 直接读取

已部署独立 .NET 8 reader 后，上述入口同样接受 `.raw`（大小写不敏感），不经临时 mzML：

```python
data = CyESIData.load_from_file("wt-1.RAW", ref_mz=760.5847, raw_timezone="Asia/Shanghai")
batch = CyESIData.load_from_directory("raw_only", ref_mz=760.5847, feature_strategy="shared")
```

760.5847 来自历史 wt-1 对照实验，其他实验应自行指定。RAW 默认采集时区为
Asia/Shanghai，显式 `raw_timezone` 优先于 `SCMM_RAW_TIMEZONE` 环境变量。
reader 保留完整 profile，遇到 centroid 扫描报错；现有下游提峰等算法保持原样。
合谱与对齐顺序重读，不把全部原始谱放入内存；最终矩阵仍需内存。

`load_from_filelist()` 的 legacy/shared/independent 均支持 RAW；目录不递归，建议输入
目录只放需要处理的文件，不要同时放同一样本的 RAW 和验证 mzML（不会自动去重）。
默认含 RAW 的 legacy 目录串行，纯 XML 沿用全 CPU；显式 `n_jobs` 覆盖；
shared/independent 仍串行。独立的 `batch_process()` 旧助手仍仅扫描 XML。

项目不提供 RAW 格式转换工具；旧 `msconvert_path` / `--msconvert` 参数已移除。
不支持 Thermo RAW 的环境仍可直接读取已有 mzML/mzXML。
安装位置、协议、结果差异和验证见 [Thermo RAW 技术说明](deployment.md#thermo-raw-额外依赖)。
网页项目入口现亦支持 Thermo profile RAW，复用本节后台路径。

### 缓存原始数据的细胞提取预览（Python API）

```python
from pathlib import Path
from scMM.application import (
    ProcessingParameters,
    RawPreviewService,
    StorageCatalog,
    StorageRoot,
)

service = RawPreviewService(StorageCatalog([StorageRoot("Raw", Path("data"))]))
raw = service.open("Raw", "sample.mzML")
parameters = ProcessingParameters(ref_mz=734.5929, baseline_filter_size=51)
preview = raw.cell_detection(parameters)
# XML 复用内存中的 experiment；RAW 每遍重新流式读取，不缓存全部原始谱。
snr_preview = raw.cell_detection(
    parameters,
    extraction_method="snr_v1",
    reference_mz=[734.5929, 760.5851],
    reference_mode="union",
)
apices = snr_preview.traces.loc[snr_preview.traces.cell_apex]
```

`traces` 包含 frame_id、rt_seconds、cell_window、cell_apex 和 reference_0 等列；
reference 列按 `preview.reference_mz` 的顺序对应实际匹配 m/z，不采用不明确的 RT/frame 混合轴。
`window_ranges` 为两端均包含的帧位置区间。SNR 参考需能在 reference_ppm_tol 内匹配。
使用完整文件的 MS1 扫描，正式提取与预览应传入相同参数；不自动保存，不保留完整基线。
这仍是完整计算，数据量大时会耗时；网页的细胞检测预览使用此 API。

`preprocess`、`load_from_file` 及 `load_from_directory` 可传
`progress_callback(value, message)`。单文件 value 表示提取阶段进度，目录为批次进度；
不是整个耗时的百分比或 ETA。回调错误直接传播。`debug_full_baseline=False` 可减少
debug hook 的完整基线内存占用；不传时保持旧 debug 行为。

### 多个原始文件作为一个连续数据集

```python
data = CyESIData.load_from_filelist(
    "data/run-01",
    ref_mz=734.5929,
    ppm_tol=10,
    n_jobs=4,
    cell_snr=5,
)
```

本例使用默认 legacy 策略，先从目录直接子文件构建合并谱和公共特征轴，再按 `n_jobs` 对齐文件；
文件按采集时间排序，所有细胞共享 0–1 的全局 `time`。它适合属于同一连续实验的多段采集。
RAW 的自动并发与其他目录策略见 [批处理模式](#目录处理与批处理模式)。

### 重新载入已有结果

```python
data = CyESIData.load_from_processed("results/sample")
```

目录中必须有 `.meta`，并至少有 `data.pkl` 或 `data.csv`。读取时优先使用 pickle；pickle 能更
可靠地保留列类型和 pandas 数据类型。

### 数据变换方法链

除 `deisotope(inplace=False)` 外，以下方法都会修改当前对象并返回自身，因此可以串联：

```python
data = (
    data.deisotope(ppm_tol=1.0, r_square_threshold=0.95)
    .remove_outlier(contamination=0.01, random_state=42)
    .impute(method="knn", missing_values=0, n_neighbors=5)
    .normalize(method="total", scale=1.0)
)
```

建议逐步运行并记录每一步前后的细胞数、特征数和零值比例，而不是第一次就全部串联。

#### 检查去同位素结果而不修改数据

本节是原 Python 回归/强度上限算法；网页数据库分子式天然分布标记保留所有峰和候选，
与本方法的删峰/求和语义不同，见[网页操作](annotation.md#查库版本与注释图表)。内部算法与网页同名功能应按各自明确的科学定义使用。

```python
audit = data.deisotope(
    ppm_tol=1.0,
    r_square_threshold=0.95,
    inplace=False,
)

candidate_pairs = audit["candidate_table"]
accepted_pairs = audit["final_table"]
```

`final_table` 包含母峰、子峰、同位素阶数、ppm 误差、回归斜率、R² 和允许的最大强度比。
`inplace=False` 不会写入 `data`、`feature_meta`、`file_meta` 或 `deisotope_result`，因此适合先做参数
审计。`merge_mode="sum"` 会把确认的子峰强度累加到母峰；是否从结果中删除子峰仍由 `remove`
独立控制。

### 质量注释

```python
hits = data.get_annotation(
    "data/structures.sdf",
    ppm_tol=5,
    search_mode="pos",
    max_results_per_mz=5,
)
hits.to_csv("results/annotation_candidates.csv", index=False)
```

`get_annotation()` 只返回候选表，不自动修改 `feature_meta`。网页候选注释按应用层登记与保存。

若只需查询少量质量，可直接使用：

```python
from scMM.util.annotation import SDFMzSearcher

searcher = SDFMzSearcher("data/structures.sdf")
hits = searcher.search([734.5929, 760.5839], ppm_tol=5, mode="pos")
```

### 访问数据

```python
print(data.get_name())
print(data.data.shape)
print(data.peak_meta.head())
print(data.feature_meta.head())

# 返回最接近目标 m/z 的整列强度；这是最近邻选择，不施加 ppm 上限
intensity = data[734.5929]

# 获取来源标签，并可选映射成实验组名
labels = data.get_labels({"sample_01": "control", "sample_02": "treated"})
```

需要严格质量容差时，不要直接依赖 `data[mz]`；应先计算最近特征的 ppm 误差并检查是否可接受。

### 保存与重载

```python
result_dir = data.save("results", overwrite=False)
print(result_dir)  # 通常为 results/<data.get_name()>

same_data = CyESIData.load_from_processed(result_dir)
```

`save()` 参数是根目录，不是最终目录。再次保存同名数据时默认抛出 `FileExistsError`；只有明确
接受覆盖时使用 `overwrite=True`。

### 转换为 AnnData

```python
adata = data.to_anndata()
```

`adata.raw` 是转换时的矩阵快照，不保证为仪器原始强度。完整映射及层/嵌入的保存含义见
[AnnData 映射](#anndata-映射)。从旧格式转换时重建唯一细胞名称并保留 `obs["source_index"]`；从 AnnData 导入的往返保留原细胞/特征 ID。

### 目录处理与批处理模式

先区分目录加载（返回一个数据集）与旧 `batch_process()` 助手（写多个单文件结果）：

| 入口 | 特征定义与执行方式 | 输出 |
|---|---|---|
| `load_from_filelist(..., processing_strategy="legacy")` | 整目录合谱，共同特征轴；文件 worker 默认 RAW=1/XML=全部 CPU | 一个连续数据集 |
| `load_from_directory(..., feature_strategy="shared")` | 共同特征、顺序逐文件；等价 `load_from_filelist(..., processing_strategy="shared")` | 一个合并数据集 |
| `load_from_directory(..., feature_strategy="independent")` | 各文件独立选峰，再按 ppm 合并；也可从 `load_from_filelist` 指定 | 一个合并数据集 |
| `batch_process()` 后 `concat()` | 旧 XML 助手，每文件独立结果，可文件间并行；再显式合并 | 多个单文件目录及合并结果 |

#### 模式 A：共享公共峰轴

```python
combined = CyESIData.load_from_filelist("raw-data", ref_mz=734.5929, n_jobs=4)
```

所有文件先共同生成公共峰轴，再形成一个连续数据集。适合连续采集或希望从一开始就共享特征
定义的数据。

#### 模式 B：先独立处理，再对齐合并

```python
from scMM.file.batch import batch_process, concat

paths = batch_process(
    "raw-data",
    "per-file-results",
    n_jobs=4,
    ref_mz=734.5929,
    ppm_tol=10,
)

combined = concat(
    "per-file-results",
    "combined-results",
    ppm_tol=5,
    ref_idx=0,
    mz_merge_options="union",
)
```

每个原始文件独立产生特征轴和结果目录，然后 `concat()` 按 ppm 对齐。适合需要检查各文件处理
质量、单独重跑失败文件，或文件并不构成一条连续时间轴的情况。

注意：`batch_process(n_jobs=...)` 的并发发生在文件之间；传给各文件加载函数的其他参数放在
`**kwargs`。不要在同一层重复传入两个 `n_jobs`。

### 手动合并两个数据集

```python
left = CyESIData.load_from_processed("results/control")
right = CyESIData.load_from_processed("results/treated")

left.alignwith(right, ppm_tol=5, mz_merge_options="union")
```

该操作原地修改 `left`：

- `union`：保留两边未匹配特征，不存在的位置填 0。
- `ref`：只保留 `left` 的特征轴。

这只是 m/z 对齐和行拼接，不会自动进行批次校正、重新归一化或时间重标定。

### 底层谱工具

高级工作流不能满足时，可以组合 `scMM.file.io`：

- `load_single_file()`：按扩展名读取 mzML/mzXML/Thermo profile RAW 和文件元数据；也可用 `format` 显式指定。
- `sum_spec()`：在变分辨率 Orbitrap 网格上汇总谱。
- `sum_spectrum_from_file()`：读取并汇总单文件。
- `extract_peaks()`：从汇总谱提取质心峰。
- `align_frame()`：把每个扫描对齐到指定 m/z 列表。
- `pack_specs()`：把多个 `MSSpectrum` 包装为实验对象。
- `save_spectra()`：把一个或多个谱保存为 mzML。

底层 API 不自动完成细胞识别和元数据封装。一般分析优先使用 `CyESIData`。

### 高级矩阵去噪工具

`scMM.util.denoise` 提供两个不属于默认预处理链的研究型工具：

```python
from scMM.util.denoise import peak_recon, r1_decomposition

a, b = r1_decomposition(X, tol=1e-6, max_iter=100)
reconstructed, noise_sigma = peak_recon(
    signal,
    baseline,
    lam=0.5,
    sigma_min=1e-3,
    tau=2.0,
    max_iter=50,
    n_jobs=4,
)
```

- `r1_decomposition` 用两个向量的外积近似输入矩阵，适合检查或提取秩一结构。
- `peak_recon` 在给定信号矩阵 `S` 和同形状基线矩阵 `B` 后，逐特征分离稀疏正峰和噪声。
- `lam` 和 `tau` 越大通常越强调稀疏性；没有通用推荐值，应使用合成峰、空白和标准品验证。
- 两个输入必须是有限、非空且形状一致的二维数组。
- 这些工具不会自动更新 `CyESIData` 的 `peak_meta` 或 `feature_meta`，因此不应把返回矩阵直接替换
  `data.data`，除非已经确认维度和语义保持一致。

下一步：[下游分析](statistics.md) 和 [数据输出](projects-and-data.md)。

#### 工作台显式子集

`AnalysisWorkspace.subset(cell_ids=[...], feature_ids=[...])` 按稳定 ID 裁剪/重排当前数据，
至少显式选择一类，另一类可省略；不使用 `CyESIData.__getitem__` 的最近 m/z 读取规则。
未知、重复或空列表拒绝并保留状态。成功同步矩阵/元数据/层，失效下游结果；`reset()` 仍恢复完整起点。


数值变换、提取和对齐在完整候选通过校验后才更新对象；插件归一化、缺失判定、调试钩子和估计器不会获得当前矩阵的可写视图。
回调失败或返回非法矩阵/元数据时保留原状态；不要依赖调试钩子写入计算输入。矩阵变换失效旧分析及其序列化报告，测量层/raw 的保留规则见[AnnData 映射](#anndata-映射)。
离群筛选仍接受 sklearn kwargs，建议显式传 `random_state`；file_meta.outlier 记录种子/随机状态和筛选数量，完整参数由调用方保存。

`assign_source_metadata(metadata_by_file, overwrite=False)` 默认拒绝已有列冲突；显式 overwrite=True 可更新标签并扩充已有分类字段。
元数据修改按报告记录的字段依赖失效相应只读结果，无关字段/同值写回保留；畸形或未知版本报告使操作失败且不更改原状态，见[报告目录](#统计与监督报告目录)。

### 离子归组、表示与完整项目

新入口为 `scMM.ion`，不改变旧 `deisotope/get_annotation`。下面的 `measured` 是已对齐、
有唯一细胞/Feature ID 与 `var['mz']` 的 AnnData；只有明确核实的未变换输入才声明线性。
同 m/z 的不同 Feature ID 不合并，稳定同位素示踪需另建模型。

```python
from pathlib import Path
from scMM.application.projects import ProjectStore
from scMM.application.data_views import (
    DataViewCatalog, initialize_catalog, add_source_view, activate_view,
)
from scMM.ion import ION_SPECS, find_relations, infer_groups, build_representations

project_root = Path("ion_projects")
project_root.mkdir(exist_ok=True)
store = ProjectStore(project_root)
project = store.create("ions")
view, branch = initialize_catalog(
    project, measured, source={"kind": "verified acquisition"},
    origin_kind="extraction", linearity="linear_abundance",
)
catalog = DataViewCatalog.from_state(project.ion_state)
source = catalog.measurement(view["root_id"])
specs = [ION_SPECS[key] for key in ("[M+H]+", "[M+Na]+", "[M+K]+", "[M+NH4]+")]
relations = find_relations(source, specs, polarity="pos", ppm=5.0)
grouping = infer_groups(source, relations["relations"], specs, ppm=5.0)
# Inspect all alternatives before specifying selections. Empty selections retain unknowns.
selections = []  # each: ec_id, hypothesis_id, relation_ids, review="accepted"
relation_reviews = {key: "accepted" for row in selections for key in row["relation_ids"]}
l1, l2, audit = build_representations(
    source, grouping, selections, relation_reviews=relation_reviews, include_singletons=True,
)
project.ion_state["registry"]["grouping"]["review-1"] = {
    "root_id": view["root_id"], "grouping": grouping,
    "selections": selections, "relation_reviews": relation_reviews,
}
for level, matrix in (("L1", l1), ("L2", l2)):
    if matrix is not None and min(matrix.shape) > 0:
        derived, derived_branch = add_source_view(
            project, matrix, root_id=view["root_id"], level=level,
            source_features=list(source.var_names), grouping_id="review-1",
            quantification_id=audit["representation_id"],
        )
store.save(project)
reopened = store.open(project.folder)
```

每个选定角色解释仍需与接受关系一致并连接全部成员，不自动选最大组或第一个解释。
固定代表可通过 selection 的 `quantifier_feature_id` 指定。
`build_exploratory_representations` 需传入公式条件比例规则评估，不把准确质量阶梯当作验证丰度。
`formula_relations` 接受显式 `feature_id/formula/species_id` 假设和实际 `resolution_200`；
`measure_evidence` 还要求原始强度溯源且未插补，信息不足应保留原因。

```python
from scMM.ion import build_compound_index, search_candidates, normalize_evidence

database = build_compound_index(
    [{"namespace": "local", "record_id": "g1", "formula": "C6H12O6", "name": "candidate"}],
    source={"kind": "local curated table", "version": "1"},
)
annotations = search_candidates(
    [{"target_id": "unknown-feature", "target_kind": "feature", "mass": 181.0707, "polarity": "pos"}],
    database, specs, ppm=5.0,
)
evidence = normalize_evidence(
    [{"kind": "experience", "target": {"kind": "feature", "id": "unknown-feature", "version": "review-1"},
      "scope": {"samples": ["sample-1"]}, "note": "user assertion; not automatic identification"}],
    source={"kind": "manual evidence", "version": "1"},
)
# Attach overlays to the catalogue registry; numerical branches remain unchanged.
project.ion_state["registry"]["annotation"]["annotation-1"] = annotations
project.ion_state["registry"]["evidence"].update({row["evidence_id"]: row for row in evidence})
```

含不可量化条目的 L2 不直接进入有限矩阵分析：

```python
from scMM.ion import preview_complete_availability
from scMM.application.data_views import materialize_analysis_branch

# Choose an existing L2 source view ID, not an AnnData layer name.
preview = preview_complete_availability(l2, cell_ids=list(l2.obs_names))
new_branch = materialize_analysis_branch(project, view_id=l2_view_id, preview=preview)
activate_view(project, l2_view_id, branch_id=new_branch,
              expected_catalog_revision=project.ion_state["revision"])
# After transformations, use a declared linear layer for FC and another layer for tests.
result = project.workspace.differential(
    "group", "a", "b", effect_layer=linear_layer, test_layer=test_layer,
)
```

`file.ion_bundle.export_project_bundle/import_project_bundle` 处理完整项目内存包，
`file.ion_view.export_compound_source/import_compound_source` 处理单源 L2；正式项目用 `ProjectStore.save/open`。
正式保存没有可执行模型；维护恢复模型继续采用已有白名单及输入验证。内部接入按上述领域与应用接口组织。

## 统一降维入口

`scMM.analysis.embedding.reduce_dimension()` 计算并写入指定 `obsm` 键，参数记录在对应 `uns` 中。
它显式选择 X 或已有嵌入；API 的 `pca_components=None` 不预先做 PCA，网页 UMAP 默认显式请求 PCA 20 维。
输入维数、邻居数及 perplexity 不合法时明确报错，不截断。以下维数必须适合实际细胞/特征规模：

```python
from scMM.analysis.embedding import reduce_dimension

embedding = reduce_dimension(
    adata,
    method="umap",
    use_rep="X",
    pca_components=20,
    n_neighbors=15,
    random_state=42,
    store_key="X_umap_review",
)
```

工作台还检查已有键不可覆盖。下方 PlotEngine 的 `pca()` 及 `umap()` 是保留的 内部绘图接口，
部分小样本参数由该接口调整，不能套用统一 API 的默认值。

## 内部 PlotEngine

#### 绘图引擎初始化

推荐从 `CyESIData` 转换：

```python
from scMM.plot.engine import PlotEngine

adata = data.to_anndata()
engine = PlotEngine.from_adata(adata, fig_path_dir="results/figures")
```

也可以从 DataFrame 初始化，并分别传入 `obs` 和 `var`：

```python
engine = PlotEngine(df, "results/figures", obs=cell_meta, var=feature_meta)
```

图目录会自动创建。大多数绘图方法把 SVG 写入该目录并返回 `self`；数值结果保存在
`engine.adata.obsm` 或 `engine.adata.uns`。

#### PCA

```python
X_pca = engine.pca(
    n_components=50,
    scale=True,
    zero_center=True,
    random_state=42,
)
```

| 参数 | API 默认值 | 含义 |
|---|---:|---|
| `n_components` | `50` | 主成分数；自动截断到样本数和特征数 |
| `scale` | `True` | 是否除以特征标准差 |
| `zero_center` | `True` | 是否减去特征均值 |
| `random_state` | `42` | 随机种子 |
| `store_key` | `X_pca` | `adata.obsm` 保存键 |
| `return_model` | `False` | 是否同时返回 sklearn PCA 模型 |

解释方差比例和处理参数保存在 `adata.uns["X_pca_params"]`。如果输入已按特征 z-score，仍可
考虑 `scale=False`，避免重复标准化。

#### UMAP

```python
X_umap = engine.umap(
    use_pca=True,
    n_neighbors=15,
    min_dist=0.7,
    metric="euclidean",
    random_state=42,
)
```

| 参数 | API 默认值 | 内部示例值 | 含义 |
|---|---:|---:|---|
| `n_components` | `2` | `2` | 输出维数 |
| `n_neighbors` | `30` | `15` | 局部近邻规模；必须在 2 到细胞数减 1 之间 |
| `min_dist` | `0.3` | `0.7` | 低维空间点的最小距离 |
| `metric` | `euclidean` | `euclidean` | 距离度量 |
| `random_state` | `42` | `42` | 随机种子 |
| `use_pca` | `False` | `True` | 是否使用已有/临时 PCA 作为输入 |
| `pca_key` | `X_pca` | `X_pca` | 已有 PCA 的 `obsm` 键 |
| `pca_n_components` | `30` | 不使用 | 没有已有 PCA 时临时 PCA 维数 |

UMAP 是可视化和近邻结构模型，不应仅凭图上距离断言精确生物学时间或连续动力学。

#### 细胞聚类

```python
engine.cluster_cells(
    method="leiden",
    key_added="clusters",
    n_neighbors=15,
    resolution=1.0,
    random_state=0,
)
```

聚类使用 `X_pca` 构建近邻图，并在 `X_umap` 上绘制结果，所以两者必须先存在。

- Leiden 需要 `python-igraph` 和 `leidenalg`。
- Louvain 需要 `networkx`。
- 标签写入 `adata.obs[key_added]`。
- `resolution` 越高通常产生更多小簇，但关系不是固定线性的。

建议报告 PCA 维数、近邻数、算法、分辨率和随机种子，并检查不同参数下结论是否稳定。

时间方法见[时间轨迹与趋势](statistics.md#实验时间与伪时间)。

#### 特征网络

```python
embedding = engine.feature_network(
    name_key="annotation_name",
    class_key="lipid_class",
    metric="pearson",
    n_neighbors=15,
)
```

该方法把“特征”而不是“细胞”嵌入二维空间，并保存带标签的距离嵌入散点图。当前输出不绘制
特征之间的网络边：

- `pearson`：根据绝对相关性构造距离。
- `euclidean`：直接比较跨细胞强度向量。
- 至少需要 3 个有效命名特征。
- `n_neighbors` 必须在 2 到特征数减 1 之间。

距离嵌入图是探索性可视化，不代表已知生化反应或直接的特征连接。

## 轻量降维接口

`scMM.plot.embedding.dimension_reduction()` 提供 PCA、UMAP、t-SNE、Isomap、LLE 的统一绘图接口，
并支持按来源标签、连续值或 DBSCAN/自定义模型着色。需要完整轨迹和结果持久化时优先使用
`PlotEngine`。

```python
from scMM.plot.embedding import dimension_reduction

result = dimension_reduction(
    data,
    method="umap",
    color="categorical",
    reduce_kwargs={"n_neighbors": 15, "min_dist": 0.1},
    plot_kwargs={"s": 8, "alpha": 0.8},
)
embedding = result["X_emb"]
ax = result["ax"]
```

各方法未覆盖时的内置起点：

| 方法 | 关键默认值 |
|---|---|
| PCA | `n_components=2`, `svd_solver="auto"` |
| UMAP | `n_neighbors=15`, `min_dist=0.1`, `n_components=2`, `metric="euclidean"`, `random_state=42` |
| t-SNE | `n_components=2`, `perplexity=30`, `learning_rate="auto"`, `init="pca"`, `random_state=42` |
| Isomap | `n_components=2`, `n_neighbors=15`, `metric="euclidean"` |
| LLE | `n_components=2`, `n_neighbors=15`, `method="standard"` |

`color="categorical"` 使用数据来源标签；`color="cluster"` 默认使用 DBSCAN，也可在
`cluster_kwargs["method"]` 中传入兼容的聚类器；一维 NumPy 数组用于连续值着色。接口会复制
聚类参数后再取出 `method`，因此可以安全地复用调用方的参数字典；聚类器必须为每个观测返回一个
标签。

## 原始谱与 EIC 绘图

`scMM.plot.msplot` 提供不依赖 `PlotEngine` 的质谱质控图。

#### 提取离子流

```python
import matplotlib.pyplot as plt
from scMM.plot.msplot import eic

fig, ax = plt.subplots()
ax, (x, intensity) = eic(
    ax,
    aligned_frames,
    mz=734.5929,
    ppm_tol=5.0,
    time=frame_times,  # 可省略，省略后横轴为行索引
)
```

`eic` 会汇总容差内的所有列；找不到 m/z 时抛出错误，而不是静默选择最近峰。

#### 绘制矩阵汇总谱

```python
from scMM.plot.msplot import plot_ms

fig, ax = plt.subplots()
plot_ms(ax, aligned_frames, frame_range=(0, 1000))
```

`frame_range=None` 默认使用全部行，范围采用 Python 的左闭右开语义。

#### 绘制单个 PyOpenMS 谱

```python
from scMM.plot.msplot import plot_spectrum

fig, ax = plot_spectrum(
    spectrum,
    mz_range=(100, 1000),
    top_n_labels=10,
    normalize=True,
    exclusion_window=10.0,
    linewidth=1.0,
    save_path="results/figures/spectrum.svg",
)
```

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `top_n_labels` | `0` | 标注最强的 N 个相互分离峰；0 不标注 |
| `mz_range` | `None` | 显示质量范围 |
| `intensity_range` | `None` | 手动 y 轴范围 |
| `normalize` | `False` | 是否除以显示范围内最大强度 |
| `exclusion_window` | `10.0` | 被标注峰之间的最小 m/z 间隔 |
| `label_fmt` | `{:.4f}` | m/z 标签格式 |
| `figsize` | `(10, 4)` | 未传入轴时创建的图尺寸 |
| `linewidth` | `1.0` | 谱线宽度 |

绘图前会移除非有限峰并按 m/z 排序；归一化只使用 `mz_range` 内最终显示的峰。峰标签按强度选择，
同时遵守 `exclusion_window`，避免在相邻峰上堆叠标注。

#### 全局绘图样式

导入 `scMM.plot` 不会修改 Matplotlib 全局配置。显式调用：

```python
from scMM.plot import configure_plotting

configure_plotting()  # 使用 scMM 字号默认值
configure_plotting("fonts/MyFont.ttf")  # 可选自定义字体
```

字体路径必须指向存在的文件。为了结果可重复，正式图形应记录字体文件或使用环境中稳定可用的字体。

## PlotEngine 时间方法

这些示例使用内部计算入口。统计页说明网页输入、时间坐标与输出边界。

```python
engine.run_palantir(
    start_idx=0,
    plotting=True,
    use_obsm="X_umap",
    knn=30,
    num_waypoints=500,
)
```

```python
engine.compute_trajectory(
    window_size=100,
    step_size=50,
    cell_dist_key="X_umap",
    parameterization_key="time",
    branch_prob_key=None,
    min_cells_per_window=5,
    plotting=True,
)
```

```python
engine.metabolic_velocity(
    window_size=100,
    step_size=50,
    parameterization_key="time",
    plot=True,
)
```

```python
engine.plot_metabolite_trends(
    parameterization_key="time",
    window_size=100,
    step_size=50,
    kernel_stat="median",
    feature_name_key="mz",
    plot_top_n=30,
)
```

```python
engine.plot_trend_clusters(
    metric="correlation",
    cluster_method="leiden",
    top_k=150,
    resolution=0.5,
)
```

### Palantir 参数与结果槽位

API 默认值：

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `start_idx` | 必填 | 起始细胞的整数位置 |
| `terminal_states` | `None` | 可选终末细胞列表 |
| `n_diff_components` | `10` | 扩散成分数 |
| `knn` | `30` | Palantir 近邻数 |
| `num_waypoints` | `500` | 路标点数量 |
| `scale_components` | `True` | 是否缩放扩散成分 |
| `max_iterations` | `25` | 最大迭代次数 |
| `seed` | `42` | 随机种子 |

起始细胞应由实验先验、时间或标志物确定，而不是为了得到期望轨迹而挑选。结果默认写入
`obs["palantir_pseudotime"]` 和 `obsm["palantir_branch_probs"]`。

### 窗口轨迹调用参数

| 参数 | API 默认值 | 说明 |
|---|---:|---|
| `window_size` | `100` | 每个窗口的细胞数 |
| `step_size` | `50` | 窗口起点步长，单位也是细胞数 |
| `cell_dist_key` | `X_umap` | 轨迹所在低维坐标 |
| `parameterization_key` | `palantir_pseudotime` | 排序细胞的 `obs` 列 |
| `branch_prob_key` | `palantir_branch_probs` | 分支权重；不存在或设为 `None` 时按单分支处理 |
| `store_key` | `trajectory` | 结果在 `adata.uns` 中的键 |
| `min_cells_per_window` | `5` | 有效窗口/分支所需最少细胞 |

内部绘图层使用实验 `time` 而非 Palantir 伪时间，并采用更大的 1000/300 窗口作为高细胞数
CyESI 数据的起点。

### 趋势调用参数

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `kernel_stat` | `median` | 窗口聚合方法：`median`、`mean`、`sum` |
| `feature_name_key` | `None` | 用作图中名称的 `var` 列；`None` 使用 `feature_序号` 名称 |
| `plot_top_n` | `None` | 是否绘制排名靠前的 N 个特征 |
| `cmap` | `viridis` | 热图颜色映射 |

每个特征的池化趋势、时间中心、相关系数、p 值、q 值和排名保存在
`adata.uns["metabolite_trends"]`。热图为了可视化会对每一行做 z-score，因此颜色表示相对趋势，
不是原始强度。

## 内部调用参数与排错

### 原始谱与细胞检测

这些参数用于原始 mzML/mzXML 和 Thermo profile RAW 的提取；RAW 的额外依赖见 [安装说明](deployment.md#thermo-raw-额外依赖)。

| 内部参数 | API 参数 | 默认值 | 含义 | 推荐与调优方向 |
|---|---|---:|---|---|
| `REF_MZ` | `ref_mz` | `734.5929`（示例值） | 用于识别细胞事件的参考离子 | **必须按实验修改**；选择稳定、细胞中高响应、空白中低响应的离子 |
| `PPM_TOL` | `ppm_tol` | `10.0` / API `10` | 扫描帧与公共峰轴的质量容差 | 高分辨且已校准数据可从 5 ppm 开始；漂移明显时尝试 10 ppm；过大会混合邻峰 |
| `RESOLUTION_200` | `resolution` | `35000` | 仪器在 m/z 200 处的分辨率 | 使用采集方法标称值；设得过高会增加网格和内存，过低会合并近邻峰 |
| `RESAMPLE_POINTS_PER_FWHM` | `resample_points_per_fwhm` | `5.0` | 每个峰半高宽的插值采样点数 | 4–6 通常是合理起点；增大提高网格密度但增加内存和时间 |
| `MS_PEAK_SNR` | `ms_peak_snr_threshold` | `10.0` | 合并谱保留峰的 SNR 阈值 | 特征过多/噪声多时增大；弱峰大量丢失时减小到 5 左右并检查空白 |
| — | `prominence_ratio` | `None` | `find_peaks` 的相对峰突出度阈值 | `None` 不施加突出度限制；噪声峰过多时可尝试 `0.001`–`0.01` |
| — | `distance` | `3` | 合并谱中相邻候选峰的最小网格点间距 | 通常保持默认；它不是 Da 或 ppm |
| `CELL_SNR` | `cell_snr` | `5.0` | 参考通道信号相对局部基线的细胞判定倍数 | 假阳性多时增大；已知细胞事件漏检时减小，并结合原始 EIC 检查 |
| `CELL_MIN_SIGNAL` | `cell_min_signal` | `1e5` | 每扫描参考离子扣基线后的最低净信号，单位与提取强度一致 | 与倍数条件同时满足；0 关闭。提高可抑制零基线区域的弱假阳性，也可能漏掉真实弱细胞 |
| `BASELINE_FILTER_SIZE` | `baseline_filter_size` | `50` | 沿扫描帧方向估计基线的中值滤波窗口 | 应明显宽于单个细胞事件；慢漂移可增大，快速基线变化可减小 |
| `MAX_ZERO_FRAC` | `max_zero_frac` | `0.90` | 允许特征为零的最大细胞比例 | `0.90` 表示至少约 10% 细胞检出；探索稀有特征时可升至 0.95–0.99 |
| `N_JOBS` | `n_jobs` | 内部目录方法 `None` | 多文件或部分特征处理的并行工作数 | legacy 目录 API 自动选择 RAW=1/XML=全部 CPU；`-1` 显式使用全部 CPU；网页取值见[提取参数](extraction.md#网页默认参数与适用范围) |

#### 合并谱底层去噪参数

高层加载接口只直接暴露 `ms_peak_snr_threshold`。需要底层控制时可调用
`scMM.util.peak.filter_spectrum`：

| 参数 | API 默认值 | 含义 | 推荐 |
|---|---:|---|---|
| `baseline_window` | `101` | 局部基线窗口，偶数会自动调整为奇数 | 覆盖数个峰宽，不能小到跟随峰顶 |
| `noise_window` | `101` | 用 MAD 估计局部噪声的窗口 | 通常与基线窗口相近 |
| `baseline_quantile` | `0.1` | 窗口内作为基线的分位数 | 0.05–0.2；峰密集时使用较低值 |
| `snr_threshold` | `3.0` | 保留信号的 SNR | 高层处理会传入显式的谱峰 SNR 参数 |
| `keep_negative` | `False` | 是否保留扣基线后的负值 | 强度矩阵通常保持 `False` |
| `baseline_stride` | `10` | 间隔多少点计算一次基线锚点 | 增大可提速，过大可能忽略快速基线变化 |

### 去同位素

此节描述 内部 Python 原有跨细胞回归去同位素接口。网页采用数据库分子式天然分布标记，
保留全部峰和候选，其参数见[网页注释与同位素](annotation.md#脂质查库与同位素参数)。两种算法和处理语义不同。

内部 API 方法
`CyESIData.deisotope()` 的默认值如下：

| 参数 | 默认值 | 含义 | 推荐与注意事项 |
|---|---:|---|---|
| `isotope_diff` | `1.003355` | 单电荷碳-13 同位素质量差 | 常规单电荷碳同位素保持默认 |
| `ppm_tol` | `1.0` | 同位素质量差匹配容差 | 先用 1 ppm；仪器误差更大时谨慎增加 |
| `max_isotope_order` | `3` | 检查 M+1 至 M+n 的最大阶数 | 常规代谢组 2–3；增大显著增加候选关系 |
| `r_square_threshold` | `0.95` | 母峰与候选同位素峰共变回归阈值 | 0.90–0.99；越高越保守 |
| `carbon13_abundance` | `0.0109` | 碳-13 自然丰度 | 天然丰度样品保持默认；同位素示踪实验不应直接套用 |
| `intensity_threshold` | `0.0` | 回归时视为缺失的低强度上限 | 有明确检出限时设置，否则保持 0 |
| `safety_factor` | `1.0` | 理论同位素强度上限的放宽系数 | 大于 1 更宽松；修改前应检查 `final_table` |
| `merge_mode` | `keep_parent` | `keep_parent` 保留母峰原强度；`sum` 把子峰加到母峰 | 定量分析通常先用 `keep_parent` |
| `remove` | `True` | 是否从矩阵删除判定的同位素子峰 | 想审计但不删除时设为 `False` |
| `inplace` | `True` | 是否直接修改对象 | `False` 返回完整判定结果字典，适合调参审计 |

去同位素依赖跨细胞强度关系。细胞数很少、存在共洗脱共调控峰或进行稳定同位素示踪时，结果
需要特别谨慎。

### 异常值过滤

内部方法调用 scikit-learn `IsolationForest`：

```python
RUN_OUTLIER_REMOVAL = True
OUTLIER_OPTIONS = dict(contamination="auto", random_state=42)
```

- `contamination="auto"` 让算法使用内置阈值；已知异常比例时可设 0–0.5 之间的小数。
- 始终固定 `random_state` 以保证可重复。
- 先查看 PCA/UMAP 和质控指标，再决定是否删除异常细胞。

### SDF 注释

此节描述 内部 Python 原接口；网页的完整候选、规则与天然同位素参数见[网页注释与同位素](annotation.md#脂质查库与同位素参数)。

| 内部参数 | API 参数 | 默认值 | 含义与推荐 |
|---|---|---:|---|
| `SDF_PATH` | `sdf_path` | `None` / API 必填 | LIPID MAPS 风格 SDF；`None` 关闭注释 |
| `ANNOTATION_PPM` | `ppm_tol` | `5.0` / API 必填 | 候选理论 m/z 容差；校准良好时 3–5 ppm |
| `ION_MODE` | `search_mode` | `pos` | `pos`、`neg` 或 `both`；应与采集模式一致 |
| `MAX_ANNOTATIONS_PER_MZ` | `max_results_per_mz` | `5` / API `None` | 每个 m/z 最多保留候选数；探索时可增加 |

自定义加合物可通过 API 的 `adducts_pos`、`adducts_neg` 传入。候选按绝对 ppm 误差排序。

### 特征轴合并参数

`CyESIData.alignwith()` 和批处理 `concat()` 使用：

| 参数 | 默认值 | 含义 | 推荐 |
|---|---:|---|---|
| `ppm_tol` | `5.0` | 两数据集特征视为同一 m/z 的容差 | 使用质量校准表现确定，通常 3–10 ppm |
| `mz_merge_options` | `union` | `union` 保留双方未匹配峰；`ref` 只保留参考数据集特征 | 探索分析用 `union`，固定面板或严格比较用 `ref` |
| `ref_idx` | `0` | `concat()` 中作为参考轴的数据集编号 | `ref` 模式下选择质量和覆盖最可靠的数据集 |

合并会原地修改参考对象；未匹配位置填 0。批次校正不是该步骤的一部分。

用 `scmm-web --config workbench.json` 或 `SCMM_UI_CONFIG` 指定，命令行优先。
这只配置实验参数；服务器路径、认证与可选资源使用独立的[资源配置](deployment.md#访问与路径配置)，不能由网页表单修改。

```json
{
  "processing": {
    "ref_mz": 734.5929,
    "mz_min": 100.0,
    "mz_max": 1000.0,
    "reference_mz": [734.5929, 760.5851],
    "reference_mode": "union",
    "baseline_filter_size": 51,
    "cell_min_signal": 100000.0,
    "feature_snr_threshold": 3.0,
    "feature_block_size": 256
  },
  "analysis": {
    "normalization": "total",
    "reduction": "pca",
    "n_components": 2,
    "n_neighbors": 15,
    "perplexity": 30.0,
    "random_state": 42,
    "model": "logistic",
    "cv": 3,
    "calibration_bins": 10
  }
}
```

只覆盖明确写出的键，省略项使用本节网页默认值。未知节/键、错误类型、非法枚举、非有限数值和
互相矛盾的范围在启动时明确失败，不静默忽略。设置的是新会话默认值，不自动加载数据或执行分析。
完整处理键与帮助以 `scMM/application/parameters.py` 为准；analysis 键也在同一模块定义。
更改文件后重新启动服务才能应用；界面手工更改不会写回 JSON。

### 数值回归依据

Quantile 按观测行计算，并列值处理与输入行排列无关。全零行保零，其他行的零值参与排名。
PQN 的同值列表与 NumPy 参考向量须一致，检查形状、有限非负值和调用方数组不变。
逐观测共同检出数存放在 `uns["scmm_workbench"]["pqn_diagnostics"]`，对应的处理历史携带独立于工作区修订号的诊断键，保存重开后继续归一化会追加记录。
KNN 等插补须保留全空特征轴，不借修复轴长度统一不同入口默认方法。
这些性质由[归一化测试](../tests/domain/test_normalize.py)和[数据测试](../tests/domain/test_data.py)维护。

### `FileExistsError`

`save("results")` 会写入 `results/<数据集名>`。同名目录存在时默认中止，以保护结果。

- 想保留旧结果：更换 `OUTPUT_ROOT`。
- 明确替换标准结果文件：设置 `OVERWRITE=True` 或 `overwrite=True`。
- 不要把输出根目录误写成现有数据集目录，否则可能产生重复嵌套。

### 找不到刚保存的结果

使用 `save()` 的返回值：

```python
result_dir = data.save("results")
print(result_dir)
```

实际路径比传入路径多一级数据集名称。

### pickle 与 CSV 重新载入结果不一致

scMM 优先读取 pickle，因为它保留数值列名、索引和可空类型。CSV 是交换格式；经过其他软件写回
后，列类型和空值可能变化。不要在仍保留旧 pickle 时只修改 CSV 并期待加载修改后的 CSV。

### 去同位素删除了可疑的真实峰

先使用 `inplace=False` 审计：

```python
audit = data.deisotope(inplace=False)
display(audit["final_table"])
```

然后考虑：

- 提高 `r_square_threshold`。
- 收紧 `ppm_tol`。
- 保持 `merge_mode="keep_parent"`。
- 设置 `remove=False` 只标注关系。
- 稳定同位素示踪实验直接关闭该步骤，或建立实验专用规则。

共调控代谢物可能同时具有很高相关性和近似质量差，因此统计关系不能替代结构证据。
