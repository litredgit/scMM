# 分析：统计、监督模型与时间轨迹

[返回文档索引](README.md) · [参数参考](parameters.md)

本页解释分析方法、统计边界及调用方式；网页操作顺序见 [工作流程](workflow.md)，
Notebook 运行开关与网页参数默认值见 [参数参考](parameters.md)。

## 入口选择

| 入口 | 数据/状态 | 适用范围 |
|---|---|---|
| 网页分析工作台 | 当前项目 AnnData，结果绑定数据修订与参数 | 交互降维、聚类、差异/Marker、相关网络、监督及 SHAP |
| `scMM.analysis` | 显式传入 AnnData | 统一降维、统计及独立监督分析 |
| `PlotEngine` | 内部 AnnData，保存图形与分析结果 | Notebook 的 PCA/UMAP、聚类、时间轨迹和代谢趋势 |
| `scMM.plot.embedding` / `msplot` | 显式输入数据或谱 | 轻量降维与原始谱绘图 |

这些接口的默认值与输出语义不同，不能互换解释。时间轨迹主要通过 Python/Notebook 使用；
上游实验轨迹及概率空间 R2/Q2 的定义见 [方法依据](#暂缓方法的依据)，恢复条件见 [roadmap](roadmap.md#明确暂缓)。

Vue/FastAPI 网页分析使用共享应用层与 Plotly 图形构建；计算仍在 Python 后端完成。
Vue 按分析面板组织控件，矩阵和可执行模型只保存在后端；报告分页展示，完整下载不受分页影响。
六步操作及重载边界见[Vue 操作](workflow.md#vue-网页项目与样本)。

### Vue 尚未接入的分析能力

当前网页尚未接入 Palantir、窗口轨迹、代谢速度、
趋势及趋势聚类、特征距离嵌入、双特征散点、采集稳定性 QC 和 QC PDF。
这些 Python/Notebook 能力继续保留；更完整的入口对应关系见
[能力覆盖](development.md#前后端能力覆盖)，后续实施及验收见 [roadmap](roadmap.md)。

Python 原有 `CyESIData.deisotope()` 基于质量间隔、过原点跨细胞回归和强度上限，可以删除/求和矩阵特征，
不修改原始 RAW。网页采用下述数据库天然分布标记，两者不互换解释；原 API 参数与只读审计示例见
[去同位素](parameters.md#去同位素)及[API 示例](python-api.md#检查去同位素结果而不修改数据)。

SDF 搜索返回一对多的精确质量候选，`get_annotation()` 不自动修改矩阵或特征元数据；
Notebook 另将误差最小候选写入摘要，完整候选仍单独保存。摘要名称不等于结构鉴定，
网页独立版本保存数据库身份、加合物、理论质量、ppm 误差及完整候选来源，见
[质量注释](python-api.md#质量注释)。

### 网页脂质候选与天然同位素

同位素比例、相关性辅助及 m/z 特征网络只接受明确记录为未归一化、未插补的强度层。
分子网络另可使用有可靠来源的 `total`/`max`/`pqn` 归一化层；插补或其他变换后的层不能作为这些强度证据。
旧 H5AD/项目没有可靠溯源时标为未知，仍可导入、常规分析和保存，但不会提供为可选证据层，
也不能通过 reset、恢复层、非负值或原始层名称变成 raw。存储与恢复规则见[强度溯源](data-output.md#强度溯源)。

网页先以一级精确质量搜索 LMSD，保留所有匹配。绝对 ppm 的三档优先于网络支持等级，最后按档内类别/加合物规则分排序；
规则只提供排序证据，不把首位候选解释为结构鉴定，不删除并列候选，也不把名称拼接成一个物质。
人工指定和规则推荐分别保存，完整候选始终可审阅。

使用固定依赖版本的 OpenMS 元素表与精细天然同位素分布，纳入加合物原子组成（包括 K 的天然同位素）。
同一 nominal 阶数内，按采集分辨率估计的一个 FWHM 合并理论细结构，使用概率加权中心和合计概率；
以观测母峰 m/z 加理论间隔定位对应特征。该近似处理分辨能力，不模拟 FTMS 相位干扰或分解混合信号。
计算保存 OpenMS 版本及截断尾概率 `1e-6`，不使用旧 API 的最大碳数估算和手工碳丰度参数。

每个样本在共同有效细胞中计算 `R_observed = sum(I_child) / sum(I_parent)`；母峰为正、子峰非负，零子峰参与统计。
与理论 `P_k/P_0` 比较，默认落在理论比例的 80%～120% 且有效细胞数达到门槛时标为命中。
质量/比例边界保留 float64 计算；比例比较只为机器舍入加入极小保护，不放宽实验容差。
样本分别记录，允许同一个峰同时拥有独立物质候选及多个同位素来源，不进行贪心唯一分配。

不同不饱和度脂质与同位素可形成仪器无法分开的混合峰，比例通过不证明信号只来自同位素。
本功能只标记、审阅及筛选输出，不删除、求和或校正实测强度；精确质量无法恢复 MS1 不能区分的结构信息。
操作见[注释与同位素](workflow.md#注释与同位素)，参数/规则见[参数说明](parameters.md#网页注释与同位素)。

相关性辅助遵循“精确质量候选 → 分样本相关 → 化学关系检查 → 支持等级 → 排序 → 人工审阅”。
全细胞保留零值，另计算双方原始强度 >0 的共同检出相关、数量和比例；常数向量或共同检出不足为不可评估，
不作为反对证据，不进入重复共识分母。不同样本细胞不混算，不推断条件；条件共识分别记录支持比例、支持样本、
未支持及方向冲突，不以相关平均值掩盖不一致。同条件复现性不能替代生物重复统计推断。

首版化学支持限同一数据库候选的不同加合物（各自满足本版本精确质量容差）及母峰/天然同位素峰
（本版本质量间隔、分辨率及理论比例检查）。化学关系和两个正相关阈值同时满足才支持候选。
单一来源去重，不递归传播、不加权汇总：等级为 0 无可用支持、1 单样本支持、2 同条件重复支持；
无支持不扣分、不删除，重复不一致另标。同分子式异构体不能据此区分结构，同类/同系物共变仅作探索。
人工否定同位素关系后，该关系不再提供化学支持；人工接受仍不能跳过质量/理论比例与相关检查。

注释分类饼图默认按 `MAIN_CLASS` 统计当前筛选特征，每个特征一次；人工选择优先，
同类别多个候选归该类、跨类归“多义”、无候选归“未注释”，标题显示候选模式及分母。
m/z 网络每个稳定 feature ID 一个节点，显示候选/类别/审核状态，边保留逐样本全细胞与共同检出相关，
另标加合物/同位素关系。绘图有边不必然支持注释，圆形布局无距离含义。

分子网络仅依据人工单选或完整候选身份唯一的稳定数据库 ID 合并；名称相同或排序第一不消除歧义。
代表离子先按各样本等权检出率，再按等权原始平均强度选择，最终按稳定 feature ID 破同分；
整个项目固定一列，可人工指定，不随显示范围或样本换离子，也不相加不同加合物。
分子与 m/z 网络的强度层不同，边可以不同；默认分子网络反映 `total` 后相对丰度共变，负相关需考虑总量约束。
条件网络要求同方向的绘图边满足重复共识，仍显示各支持样本的边；逐样本结果完整保留。
参数见[相关性辅助与图表参数](parameters.md#相关性辅助与图表参数)。

此前的质量/同位素规模检查使用下载的数据库与合成矩阵，原始机器证据为
[3,000 × 500](validation/lipid-annotation-synthetic-3000x500.json)和
[10,000 × 500](validation/lipid-annotation-synthetic-10000x500.json)，复现命令见[开发指南](development.md#脂质注释规模检查)。
这些报告不表示实验准确率或用户验收；用户已选择自行手动验证。

## 统计解释与网页分析

火山图和小提琴图消费同一份全特征比较结果。选择一两个特征不会重新缩小 BH 校正的检验族。
“隐藏零值”只影响小提琴图显示，均值、fold change、p 值和 FDR 不变；每次最多展示 12 个特征。
网页小提琴图标题中的全局 FDR 与统计表中的 p 值/FDR 均以三位有效数字的科学计数法显示
（如 `1.23e-06`）；显示格式不改变检验、校正或 CSV 导出的原始精度。
差异检验要求非负丰度，并以细胞为统计单位；需要生物重复推断时先在上游按重复汇总。

Marker 使用当前分组列，逐簇对其余已标记细胞比较；每个比较内对全部特征做 BH-FDR，
不是跨簇联合校正。分组列、检验方法或数据层改变会清除旧 Marker。
相关网络使用所选数据层，按方差选取前 N 个特征，再计算 Pearson/Spearman/Kendall 相关。
阈值作用于绝对相关系数，边保留正负号；常数特征相关为 NaN、不连边，孤立节点仍显示。
网络不是因果图、细胞邻接图或轨迹；完整相关矩阵保留在本次会话，导出报告记录节点和阈值后边表。

工作台降维输入是明确选择的 X 或 obsm；UMAP 默认启用可见的 PCA 输入选项，可关闭或修改。
已有输出键不能被工作台静默覆盖；邻居数、维数或 perplexity 不适合当前样本数时明确报错。
统一 API 与 PlotEngine 的区别见下方入口说明。

网页监督分析的“验证方式”默认要求独立来源字段；选择细胞级探索后可不按来源分组。
监督分析按所选独立样本列划分训练/测试和 CV；不选时是细胞级划分，可能存在泄漏。
全数据插补/选特征引入的泄漏不能靠分组划分自动补救。潜变量仅对 PLS-DA 和支持 transform 的
LDA 开放；lsqr 仍可做分类。未标注细胞的潜变量为 NaN，额外保存 train/test/unlabeled 标识。
AP 不标为梯形 PR AUC，Brier 宏平均定义和校准诊断说明见 [概率诊断](#监督模型与概率诊断)。

SHAP 复用已训练模型及其训练折拟合的预处理：背景抽自训练集、解释样本抽自测试集，
可通过 `shap_background`/`shap_samples` 调整上限，种子沿用 `random_state`。
显示与导出跨样本（多输出时再跨类别）的平均绝对 SHAP；图展示前 30 项，CSV 包含全部特征。
这不是效应方向或因果贡献，不同模型输出空间的 SHAP 数值不能直接横向比较。
更改模型参数或重新训练会清空解释；只改 SHAP 参数会清空解释但保留模型。
SHAP 需要 supervised 可选依赖，缺失时明确报错，不自动安装；通用解释器在高维数据上可能较慢。

## 监督模型与概率诊断

独立监督分析也可直接使用 AnnData，不必创建 PlotEngine：

```python
from scMM.analysis import SupervisedAnalyzer

analyzer = SupervisedAnalyzer(adata, "condition", group_key="sample")
result = analyzer.evaluate("logistic", cv=3, calibration_bins=10)
diagnostics = result["probability_diagnostics"]
pr_curves = analyzer.precision_recall_curves()
calibration = analyzer.calibration_curves()
```

数据须提供足够的独立样本，使 holdout 和各 CV fold 均包含所有类别。
诊断仅使用 holdout，不新增训练。AP 是 average precision，不是梯形积分 PR AUC；
`brier_macro` 为每类 one-vs-rest 概率均方误差的无权平均，不是各类别误差之和。
校准曲线采用 quantile 分箱，重复/空分箱可能使返回点数少于 calibration_bins；
这只是可靠性诊断，并不重新校准概率。不要据 holdout 反复调参。

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

工作台还检查已有键不可覆盖。下方 PlotEngine 的 `pca()` 及 `umap()` 是保留的 Notebook 接口，
部分小样本参数由该接口或 Notebook 调整，不能套用统一 API 的默认值。

## Notebook 与 PlotEngine

### 绘图引擎初始化

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

### PCA

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

### UMAP

```python
X_umap = engine.umap(
    use_pca=True,
    n_neighbors=15,
    min_dist=0.7,
    metric="euclidean",
    random_state=42,
)
```

| 参数 | API 默认值 | Notebook 值 | 含义 |
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

### 细胞聚类

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

### 实验时间与伪时间

原始加载自动创建的 `obs["time"]` 表示采集进程：

- 单文件：`rt / max(rt)`。
- 多文件：按文件采集时间与帧内保留时间映射到整个批次的 0–1 区间。

它不是小时或分钟。若已知真实时间，可添加：

```python
data.peak_meta["true_time_h"] = data.peak_meta["time"] * 12
adata = data.to_anndata()
```

这只有在“整个采集跨度确实对应 12 小时”时才成立。离散实验组时间不应简单假定细胞在组内
均匀变化。

### Palantir 伪时间

```python
engine.run_palantir(
    start_idx=0,
    plotting=True,
    use_obsm="X_umap",
    knn=30,
    num_waypoints=500,
)
```

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

### 滑动窗口轨迹

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

算法先按参数化列排序细胞，再在每个细胞窗口内计算低维坐标中心。若给定分支概率，会分别对
每个分支进行加权。

| 参数 | API 默认值 | 说明 |
|---|---:|---|
| `window_size` | `100` | 每个窗口的细胞数 |
| `step_size` | `50` | 窗口起点步长，单位也是细胞数 |
| `cell_dist_key` | `X_umap` | 轨迹所在低维坐标 |
| `parameterization_key` | `palantir_pseudotime` | 排序细胞的 `obs` 列 |
| `branch_prob_key` | `palantir_branch_probs` | 分支权重；不存在或设为 `None` 时按单分支处理 |
| `store_key` | `trajectory` | 结果在 `adata.uns` 中的键 |
| `min_cells_per_window` | `5` | 有效窗口/分支所需最少细胞 |

Notebook 使用实验 `time` 而非 Palantir 伪时间，并采用更大的 1000/300 窗口作为高细胞数
CyESI 数据的起点。

### 代谢速度

```python
engine.metabolic_velocity(
    window_size=100,
    step_size=50,
    parameterization_key="time",
    plot=True,
)
```

每个时间窗口内，对每个特征做强度随时间的一阶局部回归。所有特征斜率组成速度向量，其
欧氏范数作为总体代谢速度。结果在 `adata.uns["metabolic_velocity"]`：

- `state_centers`
- `velocity_field`
- `speeds`
- `time_centers`
- `counts`
- `window_starts`

如果窗口内所有时间相同，回归分母为零，该窗口无法产生有效速度。

### 代谢趋势

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

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `kernel_stat` | `median` | 窗口聚合方法：`median`、`mean`、`sum` |
| `feature_name_key` | `None` | 用作图中名称的 `var` 列；`None` 使用 var names |
| `plot_top_n` | `None` | 是否绘制排名靠前的 N 个特征 |
| `cmap` | `viridis` | 热图颜色映射 |

每个特征的池化趋势、时间中心、相关系数、p 值、q 值和排名保存在
`adata.uns["metabolite_trends"]`。热图为了可视化会对每一行做 z-score，因此颜色表示相对趋势，
不是原始强度。

### 趋势聚类

```python
engine.plot_trend_clusters(
    metric="correlation",
    cluster_method="leiden",
    top_k=150,
    resolution=0.5,
)
```

支持的 `cluster_method` 为 `leiden`、`louvain`、`kmeans` 和 `agglomerative`，具体额外参数通过
`**kwargs` 传入。
相关距离适合比较曲线形状；欧氏距离同时受幅度影响。无法形成有限趋势的特征会标记为无效，
不应强制归入某个生物学簇。

### 特征网络

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

### 提取离子流

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

### 绘制矩阵汇总谱

```python
from scMM.plot.msplot import plot_ms

fig, ax = plt.subplots()
plot_ms(ax, aligned_frames, frame_range=(0, 1000))
```

`frame_range=None` 默认使用全部行，范围采用 Python 的左闭右开语义。

### 绘制单个 PyOpenMS 谱

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

### 全局绘图样式

导入 `scMM.plot` 不会修改 Matplotlib 全局配置。显式调用：

```python
from scMM.plot import configure_plotting

configure_plotting()  # 使用 scMM 字号默认值
configure_plotting("fonts/MyFont.ttf")  # 可选自定义字体
```

字体路径必须指向存在的文件。为了结果可重复，正式图形应记录字体文件或使用环境中稳定可用的字体。

## 暂缓方法的依据

问题来自上游 `f961809`，未移入当前项目；现有 Palantir 与时间分析接口保留。

| 上游名称 | 实际计算及边界 |
|---|---|
| diffusion / DPT | SpectralEmbedding 后到根的欧氏距离，不等同于完整 DPT 方法 |
| graph / kNN geodesic | 欧氏 kNN 图最短路；需定义断连分量和缺失值规则 |
| PCA pseudotime | PC1 到根的绝对差，根两侧折到同一方向，不表示分支命运 |
| PAGA-like | 簇中心最小生成树距离加细胞到簇中心距离，不保证指定根为起点 |

反例：`X=[0,2,4,10,12,14]`，前三/后三各一簇，根为第一个细胞，cluster graph 约输出
`[0.167,0,0.167,1,0.833,1]`。直接减根值会产生负值，截断又会合并不同位置。
恢复前应确定根、方向、分支和断连语义；可以保留现有方法、明确命名为实验性图距离，或按指定参考重新实现。
重复坐标邻居按索引排除自身已修复，不表示这些轨迹方法已验收。

上游 R2/Q2 在 one-hot 标签 Y 与类别概率 P 上计算方差加权 `r2_score`：

```text
1 - Σ(Y - P)² / Σ(Y - 训练集类别比例)²
```

R2 用训练概率，Q2 用训练集 OOF 概率；既不是 X 的解释方差，也不是独立 holdout 结果，
不能直接标成泛指的 PLS R2X/R2Y/Q2。负值表示弱于常数类别比例基准。
若确需新增，应明确命名、响应编码/缩放和基准，采用单轮分组 CV 同时生成指标与 OOF，
避免上游 cross_validate + cross_val_predict 重复拟合。当前已有 holdout ROC、PR/AP、Brier 和校准诊断。

下一步：[数据模型与输出](data-output.md)。

## 分类权重、SHAP 与展示边界

分类 Marker 为逐组对其余组的正则化逻辑回归系数排名，并非拟合其他模型预测的代理解释。
每折仅在训练折拟合标准化，符号稳定性为各折与全数据拟合权重同号的比例；这不是生物重复层面的显著性。
各模型提供留出集混淆矩阵（计数/行归一化显示切换及完整下载），LDA 同样适用；完整报告记录种子、划分方式、实际折数和训练/测试细胞。
SHAP 提供类别解释、蜂群、单细胞瀑布、依赖图和全局重要性；导出完整张量、输入值、基准值及观察 ID。
逻辑回归线性解释器的输出为对数几率，树/模型概率解释为概率，瀑布图的基准和贡献必须在相同输出空间相加。
线性二分类解释原生正类，查看负类时对贡献及对数几率基准取反；跨类/细胞平均绝对贡献不表示方向或因果。
解释器的背景只从训练集抽取，展示细胞只从留出集抽取，随机种子与实际背景记录可追溯。

热图、细胞联动及论文导出操作见[网页流程](workflow.md#论文图细胞联动与热图)，数值默认与阈值见[参数](parameters.md#新增分析控件)。
