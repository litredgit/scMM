# 数据模型与输出文件

[返回文档索引](README.md) · [Python API](python-api.md)

本页集中定义数据结构、持久化文件及恢复边界；保存调用见 API，网页保存操作见 [工作流程](workflow.md#保存和离开)。
标准数据集目录、Notebook 图目录与网页项目目录是三种不同输出，以下分别说明。

Vue/FastAPI 沿用现有项目清单和快照格式，无需迁移已有目录。
Vue 浏览器工作区及其修订号只用于当前会话并发控制，不写入 `project.json`；项目磁盘修订仍由主动保存递增。
内存工作区不等于保存快照，刷新或服务重启不会恢复未保存修改，详见
[Vue 会话操作](workflow.md#vue-网页项目与样本)。

## `CyESIData` 数据模型

一个处理后的数据集由四部分组成。

### `data`

pandas DataFrame，行是细胞事件，列是 m/z 特征，值是对应强度。

- 原始处理后未检出的峰通常记为 0。
- 列名可转换为浮点 m/z。
- 去同位素、填补和归一化会修改该矩阵。

### `peak_meta`

与 `data` 行一一对应的细胞元数据。常见列：

| 列 | 含义 |
|---|---|
| `rt` | 原始文件内的保留/扫描时间 |
| `time` | 归一化到 0–1 的采集进程 |
| `label` | 来源文件名去掉扩展名后的标签 |

具体列还取决于 PyOpenMS 读取和帧对齐结果。删除异常细胞时 `peak_meta` 会同步过滤。

### `feature_meta`

与 `data` 列一一对应的特征元数据。基础列为：

| 列 | 含义 |
|---|---|
| `mz` | 特征的数值 m/z |

运行去同位素后还可能包括：

- `deisotope_role`：`unique`、`parent` 或 `isotope`。
- `isotope_parent`、`isotope_order`。
- `isotope_slope_A`、`isotope_r_square`、`isotope_ppm_error`。
- `isotope_children` 和每阶 M+n 的详细字段。

参数化 Notebook 注释后还可能包括：

- `annotation_name`
- `annotation_formula`
- `annotation_adduct`
- `annotation_ppm_error`

### `file_meta`

普通字典，保存数据集级元数据：

- `name`
- `ref_mz`
- `length`
- 仪器和采集时间，或多文件的 `per_file_meta`
- 去同位素处理参数和删除数量

它不能自动记录 Notebook 中的所有分析开关。正式分析建议额外保存参数单元、运行日志和 Git
提交 ID。

## 保存目录

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

Python 离线读取可信旧结果时优先选择 pickle；网页拒绝 pickle，应先离线转换为 H5AD。CSV 主要用于交换。CSV 往返可能把数值列名或可空数据类型转换成字符串。

通过网页后台处理时，同一结果目录还会增加：

| 文件 | 用途 |
|---|---|
| `scmm-manifest.json` | 输入路径、完整处理参数、软件版本、质量提示和产物列表 |
| `quality-summary.json` | 细胞数、特征数、零值比例和中位质量指标 |
| `cell-quality.csv` | 每个细胞事件的总强度、检出特征数及可用采集元数据 |
| `feature-quality.csv` | 每个 m/z 的检出率、均值和非零中位强度 |
| `embedding.csv` | 固定种子的 PCA，以及依赖与数据规模允许时的 UMAP 坐标 |

这些文件不改变 `CyESIData.load_from_processed()` 所需的标准文件，可按需要与标准结果一起归档。

## Notebook 输出

默认目录关系：

```text
results/
├── <数据集名>/
│   └── scMM 标准数据文件
├── figures/
│   ├── umap.svg
│   ├── trajectory.svg
│   ├── metabolic_velocity_speed.svg
│   ├── metabolite_trends_top<N>.svg
│   ├── leiden_<key>_umap.svg
│   ├── trend_clusters_<method>_<metric>.svg
│   ├── stability_monitor_boxplot.svg
│   ├── stability_cell_counts.svg
│   ├── stability_median_correlation.svg
│   └── feature_ratio_umap.svg
├── annotation_candidates.csv
└── total_sum_spec.mzML
```

只有启用相应功能时才会生成对应文件。`total_sum_spec.mzML` 仅适用于原始目录输入。

## AnnData 映射

`data.to_anndata()` 产生：

```text
AnnData
├── X      ← 细胞 × 特征强度
├── obs    ← peak_meta + source_index
├── var    ← feature_meta
├── raw    ← 转换时的 X/obs/var 快照
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

`adata.raw` 是调用 `to_anndata()` 时的数据快照，不一定是原始仪器强度：如果先对 `CyESIData`
归一化或去同位素，raw 同样反映变换后的数据。

## 当前网页项目保存

六步网页使用 `ProjectStore`，项目默认位于 `~/data/results`（可由 `--project-root` 指定），与 CLI/API 的标准结果目录不同。
`project.json` 记录样本、参数、修订号和当前产物引用；`processing/` 保存批次请求、状态及日志，
`snapshots/` 保存发布所需的当前数据 H5AD、`baseline.h5ad` 和 `views.json`。
新项目目录使用 `项目名_YYYYMMDD-HHMMSS_短ID`，提取批次目录使用 `YYYYMMDD-HHMMSS_batch_短ID`，
快照目录使用 `YYYYMMDD-HHMMSS_r修订号_短ID`；名称中的时间为北京时间，清单时间戳仍保存 UTC。
当前数据与独立导出 H5AD 默认使用 `项目名_批次标签_YYYYMMDD-HHMMSS_r修订号.h5ad`；
未填写批次时省略，同名批次去重，多于两个批次时保留前两个并注明总数。
非法文件名字符替换为下划线，项目名和批次标签分别限制长度；短 ID 保证新目录彼此独立。
旧目录与固定 `current.h5ad` 继续按清单引用重载，不自动重命名。
独立导出默认保存在项目 `exports/`，允许修改新文件名，实际保存路径在网页显示；不会覆盖已有文件。
清单同时记录当前数据来源路径，供结果引用检查使用。

细胞预览的冻结请求与阶段状态位于 `processing/preview-jobs/<任务 ID>/request.json`、`state.json`，
预览产物仍使用 `processing/preview-<ID>/`，沿用输入身份、参数、共同特征及产物完整性校验。
预览任务不会列入提取批次，也不直接发布 `project.json`；只有当前会话接收有效结果并主动保存后，
清单才包含对应预览引用。阶段状态保留诊断与发布前活跃任务检查，不提供预览会话恢复。

新提取批次冻结输入文件身份，在执行前、共同特征构建后及逐样本提取前后检查；成功 H5AD 与共同特征轴保存 SHA-256 摘要。
重试只复用身份、参数及摘要一致的成功产物。旧批次可继续查看和审核，缺少冻结身份时须新建批次，不能直接重试复用。
`views.json` 兼容既有 Panel 图形 JSON 字符串和 Vue 图形对象；Vue 分组分析设置及逐图图例也保存于视图数据。
图表表格显示可采用科学计数法，CSV 下载保留后端原始数值精度；分页展示不截断完整下载。

点击“保存项目”先写完整快照再发布清单，跨会话保存检查修订冲突。重载恢复当前数据和完整
预处理起点，图和报告为只读记录，不恢复可执行模型；数值矩阵只提供一个当前版本，不提供历史分支。
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

Vue 默认收起内部快照、提取产物和缓存，优先打开项目以完整恢复。选择“导入已有结果”后，
按当前存储/目录的保存时间预选最新可用矩阵（项目当前快照或独立 H5AD，包含项目 `exports/` 的直接导出文件）；
恢复起点、旧快照、预览缓存和逐样本产物不参与默认预选。仅预选，不自动导入，仍可手动改选或展开内部文件。
项目快照按清单保存时间排序，独立文件按文件修改时间排序；复制文件可能改变修改时间，需结合用途核对。
当前项目只提供一个完整恢复版本；旧快照 H5AD 可作为矩阵导入，不提供历史项目分支恢复。

### 脂质注释版本与导出

`AnnData.uns["scmm_lipid_annotations_json"]` 保存 schema 1 的 JSON，包含 `active` 版本 ID 及 `versions`。
每个注释版本保存时间、名称、数据库文件摘要/来源、参数、评分规则、完整候选、逐样本同位素关系、
人工指定及核对进度、分布算法版本和不能计算的候选诊断。候选和关系使用稳定 ID，重复 m/z 的不同 feature ID 分开处理。
`var` 的 `lipid_candidate_ids`、`lipid_isotope_match`、`lipid_annotation_version` 是当前版本的索引/标记，
完整物质名称逐条保存在候选和关系表中；不使用 `/` 合并候选名称，不覆盖用户原有名称字段。

版本输入身份包含特征 ID/mz、细胞 ID、样本分组和选定强度层的完整 float64 内容。
保存重载不依赖内存工作区 ID、当前数据库可用性或可执行模型。矩阵变换后元数据仍可携带历史证据，
页面验证来源身份后才允许作为当前结果审阅/下载，不能把已过期的 var 标记当作有效当前结论。
不变原始输入层上的普通归一化不使注释失效；细胞/特征裁剪、分组或该强度层改变使版本过期。

独立导出 H5AD 含当前矩阵及这些注释版本，但仍不含项目完整恢复起点。
筛选矩阵 CSV 仅按稳定特征 ID 裁选当前矩阵列，细胞不裁剪、不重复，不按当前分页或核对的单个特征截断。
候选 CSV 按一对多候选逐行保留名称、分子式、数据库 ID、极性/加合物、质量误差和评分证据；
完整同位素 CSV 另保存母/子 ID、来源候选、样本、阶数、理论/实测比例和人工状态。
筛选不修改 `X`、layers、SNR 或恢复起点，也不影响已有数值模型。
删除前显示用途、文件数量及总大小，并重新核对引用；重开项目记录的自身目录来源不阻挡真正无引用的旧快照。
不应手动删除清单引用的文件。
原始谱仅引用路径、不复制；项目保存不能替代原始文件备份。操作入口见[网页指南](workflow.md)。

网页删除统一移动到开发/生产共享的 `~/data/results/recycle/<北京时间_短ID>/payload`，不读取或迁移旧回收条目。
`record.json` 记录原路径、类型、删除时间及预览身份。执行前重新核对文件树身份，并在项目锁下检查
清单、H5AD 溯源、活动网页会话及未结束任务；引用检查覆盖已配置存储中的可识别项目。
项目整体删除包含自身快照及任务产物，不移动清单引用的外部原始谱。
恢复保留原目录名和文件内容，须位于当前开放存储，拒绝覆盖、越界、符号链接及缺失父目录。
跨文件系统移动先复制并校验内容，再发布目标及删除源；复制失败保留原内容。回收操作共用目录锁。
移入回收区不释放磁盘空间；网页“清空回收区”直接永久删除全部共享条目，不二次确认。
清空前核对完整清单、引用、活动任务及符号链接；部分失败报告已清理数量和剩余条目。
其他进程或未配置存储中的引用无法全部发现，回收区也不替代备份或自动保留策略。

## 输出可重复性清单

每次正式运行建议同时归档：

1. 原始 Thermo RAW / mzML / mzXML 的只读副本或校验和。
2. `uv.lock` 和 `pyproject.toml`。
3. Git 提交 ID：`git rev-parse HEAD`。
4. Notebook 参数单元或单独的参数 YAML/JSON。
5. 日志输出。
6. scMM 标准结果目录。
7. 完整候选注释，而不只保留最佳候选。
8. 若后续依赖 `engine.adata` 中的分析结果，额外保存 H5AD。

## 建议的项目数据目录

原始数据通常较大，不建议直接提交 Git：

```text
project/
├── raw-data/           # 只读原始谱，不提交 Git
├── metadata/           # 样本表、实验设计、SDF 来源说明
├── results/
│   ├── processed/
│   ├── figures/
│   └── tables/
├── notebooks/          # 如有实验专用 notebook
└── run-parameters/     # 每次分析的参数快照
```

本仓库根目录的 `scMM_workflow.ipynb` 是通用模板；实验专用副本可以放到分析项目中，避免把
大量执行输出和本地路径写回软件仓库。

下一步：[常见问题与调优](troubleshooting.md)。


## 监控与项目快照的边界

监控 SQLite 独立保存最近 24 小时资源分钟汇总、页面登记摘要和账号最近访问/实际操作时间；
与认证 SQLite 分开，位于仓库和网页浏览根之外。两者都不属于实验项目，不进入项目快照、H5AD 或导出包。
监控只读取项目和任务的少量状态元数据，不读写实验矩阵；打开项目的来源仍由原项目清单和工作区管理。
页面失联记录不会随 24 小时曲线自动清除；维护及保守更新判断见[管理员监控](workflow.md#管理员监控)。
