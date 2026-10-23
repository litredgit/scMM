# 时间轨迹与趋势

[任务导航](README.md) · [架构职责](development.md)

## Notebook 与 PlotEngine

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

网页在“分析 → 伪时间与轨迹”中按稳定细胞 ID 指定根点，明确选择当前 X、强度层或已有嵌入。
输入表示直接用于扩散计算，不隐式选 PCA 或预先缩放；多尺度成分缩放由 `scale_components` 单独控制。
这与 [Palantir 扩散映射接口](https://palantir.readthedocs.io/en/latest/utils.html)的表示输入一致，
具体实现版本随结果记录。Python `PlotEngine` 下例中的 `use_obsm` 只决定绘图坐标，计算仍使用 X，
不可据此推断网页输入。根点须来自实验先验；终末 ID 留空才由算法推断。

网页检查实际扩散核和缩放后的多尺度近邻图连通性，后者对照锁定 Palantir 的最短路输入构建；
任一断连都在算法补边前拒绝计算。旧 Python 默认不新增该检查。
网页明确检查细胞量、有限输入、成分/近邻/路标范围。分支概率必须非负、逐行和为 1；
仅允许 `64 × float64 eps × max(细胞数, 分支数, 1)` 的上界及行和浮点误差，原值不裁剪或归一化。
记录所选根点、实际最早细胞、终末 ID、输入表示、参数、seed 和依赖版本。固定所选根点默认开启；
关闭时保留算法选择边界点的既有行为。伪时间是无量纲算法坐标，不解释为真实时间或因果方向。

每次计算独立命名，重复/失效旧键不覆盖；只在完整候选通过检查后一次应用。
读取、绘图、保存重开及下载均复用原数值。绘图坐标另选至少二维的已有嵌入，图中标出所选根点。
完整 ZIP 包含逐细胞伪时间/熵/全部分支概率、多尺度坐标与参数/分支名称/来源元数据；当前分析报告也收录有效结果。
持久化与失效边界见[命名时间结果](data-output.md#命名时间结果)，网页默认和工程上限见[时间分析参数](parameters.md#网页时间分析参数)。

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

网页明确选择坐标、时间列和时间含义：归一化采集进程（0–1）、采集秒数、自定义实验时间及伪时间。
导入的同名 `time` 列不自动解释；本服务产生的 Palantir 列必须声明为伪时间。
单位分别为 `unitless`、`s`、显式自定义单位和 `unitless`。不从显示行号猜时间。
窗口和步长以细胞数计，不是固定时长；排序沿用 NumPy `argsort`，完整导出保留实际排序位置。
窗口超过细胞总数时截断并记录请求/实际值，末尾不足步长时补最后一个完整尾窗。
分支键留空为单分支等权；显式指定但缺失/无效时拒绝，不沿用 Python 入口的静默单分支回退。
坐标或权重非有限的细胞不计入该窗口有效数；零权重细胞不贡献中心但仍计入有限细胞数。
不足最少有限细胞或权重和为零的窗口保留为空，图不跨空窗连线。
中心按全部坐标维度计算，图显示前两维。导出全部窗口的中心、时间、有效细胞数、权重和以及逐细胞输入/排序。
下例仍是既有 Python 入口及其默认值。

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

网页在“分析 → 伪时间与轨迹 → 窗口代谢速度”复用同一算法，使用当前 X 或显式强度层，
按所选时间递增排序；每个特征斜率单位为输入强度/所选时间单位，范数保持该量纲。
正负斜率仅表示沿所选时间坐标的增减，不是同位素示踪代谢通量。归一化时间和伪时间的速度没有秒/小时含义；
不同强度层、归一化尺度、特征集和时间尺度的范数不能直接比较。
不足 2 个细胞或相同时间窗口保留未定义值，不插值、不跨空窗连线。
结果独立命名、输入身份复核、按时间依赖失效、主动保存及完整导出见[网页流程](workflow.md#伪时间与窗口轨迹)。

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
| `feature_name_key` | `None` | 用作图中名称的 `var` 列；`None` 使用 `feature_序号` 名称 |
| `plot_top_n` | `None` | 是否绘制排名靠前的 N 个特征 |
| `cmap` | `viridis` | 热图颜色映射 |

每个特征的池化趋势、时间中心、相关系数、p 值、q 值和排名保存在
`adata.uns["metabolite_trends"]`。热图为了可视化会对每一行做 z-score，因此颜色表示相对趋势，
不是原始强度。


网页“代谢物窗口趋势”使用独立输出键，显式选择 X/强度层、时间列、含义/单位及精确稳定特征 ID（空白为全部）。
名称默认来自稳定 ID；可指定 `var` 列，缺失/空名称回退到 ID，重复名称保留 ID 区分；不存在的名称列拒绝。
网页与 Python 复用同一窗口池化、Spearman、BH 及排序算法，不改写 X、层或源趋势值；BH 只使用所选特征中的有限 p 值。
NaN 按原 reducer 忽略：全空特征窗口的 median/mean 为未定义，sum 沿原定义为 0；导出逐窗口/特征有限细胞数，
不能把该 0 当作有效测量。网页拒绝无限值及数值溢出，失败保留原工作区。
相同时间、常量趋势或不足 3 个有效窗口不产生可解释的相关/p/q，保留未定义值；有效窗口数也不是生物重复数。
重叠窗口有相关性，Spearman/BH 数值仅用于探索性排序，不作独立实验重复的显著性证据或时间因果推断。

网页热图默认显示排名前 30 个特征，并按每行有限窗口值做总体标准差的 z-score；常量行显示为 0，全空行仍为空。
可关闭显示标准化，显示原窗口统计量；横轴为递增时间排序的窗口序号，悬停和完整窗口表保留原始时间中心和单位。
显示数量和标准化独立于计算参数，重新绘图不重算趋势。全部特征统计、原窗口趋势及有限细胞数均可完整下载，
不受热图前 N 项或页面 200 行限制。伪时间、归一化采集进程与物理时间分别声明；不能把趋势当作代谢通量。

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

网页“趋势聚类”只接受 TIME-03 的有效命名趋势结果，复用已计算窗口值，不重新计算趋势或改变 X/层。
与 `PlotEngine.plot_trend_clusters()` 一样，先按每特征窗口的有限均值及总体标准差标准化，再调用原四种聚类算法；
常量变为 0，含未定义窗口的曲线标为 -1，不强制归组。全空 sum 沿原统计得到 0，可能成为零曲线，必须结合导出的有限细胞数和有测量窗口数解释。
`top_k=null` 使用原特征顺序全部曲线；显式 N 才按原趋势排名选择，实际稳定 ID、来源结果 UUID 及参数一起记录。

距离仍为 correlation/cosine/euclidean/sqeuclidean。原距离辅助函数把未定义距离替为整个矩阵的最大有限值（包含对角线 0），
再置对角线为 0；常量相关/零向量余弦会触发该规则，结果显式记录替代对数，不把它当作已知生物距离。
KMeans 继续使用原 `n_init=20`、按 correlation/cosine 默认归一化（correlation 另中心化），并记录实际参数；
Ward 继续在标准化曲线的欧氏空间拟合，即使所选距离是平方欧氏，导出的所选距离矩阵也不能解释为 Ward 拟合目标。
其他层次连接使用所选距离，图聚类保留原 kNN 边、指数距离权重、Leiden RBConfiguration 或 igraph multilevel 定义，不切换到细胞图算法。
显式固定当前依赖的既有默认：Leiden 两次迭代、max_comm_size=0；Louvain resolution=1、return_levels=false，并写入生效参数。
请求簇数与 KMeans 实际簇数不一致时保留收敛诊断和实际组数。

网页 seed 默认 0；Leiden 通过显式 seed，Leiden/Louvain 另在独立短进程中设置私有 igraph 随机源，避免改变服务内其他分析的 RNG。
所有实际拟合在单并发短进程中执行，诊断随本任务返回，不修改服务的全局警告过滤器。
层次聚类无随机步骤，单个有效特征直接成组；二者实际 seed 记 null，保留请求值。记录 NumPy/SciPy/scikit-learn 及所用图依赖版本；
相同实现/依赖/seed 的本机合成重算核对与只读重载分别验证，不承诺跨版本标签编号一致。
每个簇图保留全部成员标准化曲线和均值；特征分组、原/标准化曲线、有限计数、完整所选距离表及时间窗口可下载，读取/重开不重新聚类。
来源结果或其时间/强度/名称/特征轴依赖失效时，聚类及图同样失效；分组仅是探索，不证明代谢通路、细胞命运或因果。

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

监督模型的[概率空间 R2/Q2 依据](analysis.md#概率空间-r2q2-的依据)单独维护。
