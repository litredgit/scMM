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

这些接口的默认值与输出语义不同，不能互换解释。网页已接入下述 Palantir 和窗口轨迹；
上游实验轨迹及概率空间 R2/Q2 的定义见 [方法依据](#暂缓方法的依据)，恢复条件见 [roadmap](roadmap.md#明确暂缓)。

Vue/FastAPI 网页分析使用共享应用层与 Plotly 图形构建；计算仍在 Python 后端完成。
Vue 按分析面板组织控件，矩阵和可执行模型只保存在后端；报告分页展示，完整下载不受分页影响。
六步操作及重载边界见[Vue 操作](workflow.md#vue-网页项目与样本)。

### Vue 尚未接入的分析能力

当前网页已接入窗口代谢速度和代谢物窗口趋势；趋势聚类仍待接入。
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

网页聚类独立选择 X 或已有嵌入；DBSCAN 邻域、图聚类分辨率及常用算法参数现可显式设置，
具体白名单及各入口默认值见[网页参数](parameters.md#网页默认参数)。聚类只新增观测标签，不变换矩阵。
DBSCAN 的 -1 为噪声，不能当作生物簇；全部噪声是允许的结果。参数、输入表示和 seed 记入处理历史，
同一输出列不能覆盖，调整参数须用新列名；保存重载保留标签与实际参数，不自动重算旧项目。

“双特征散点”使用当前矩阵或明确选择的强度层，按两个不同的稳定特征 ID 精确取值，
不沿用 Notebook 数值质量输入的最近峰匹配。可按样本/来源/分组列着色：数值列用连续色条，
类别列用图例，缺失或非有限着色不排除其有限两轴数值。零值参与散点和回归；非有限两轴值仅从显示/拟合排除，
完整作图表仍包含其原行、稳定细胞 ID 及 `included` 标记。
可选回归是全部有限细胞的普通最小二乘 y 对 x，不按着色组分别拟合；报告斜率、截距、R²、p 值和标准误。
x 为常量或少于两个有限细胞时不拟合；y 为常量只显示常量线，不报告 R²/p/标准误；极端数值尺度无法稳定拟合时保留散点而不输出无效拟合。
仅两个细胞的拟合、细胞级 p 值和着色分组均不能替代生物重复或因果证据。
图及完整细胞/回归表随项目保存，重开可“读取已保存散点”；强度变换使其失效，修改相关来源/着色字段也须重绘。

“特征距离嵌入”对所选强度矩阵的特征列计算成对距离，再用预计算距离 UMAP 生成二维坐标。
Pearson 定义沿用 `PlotEngine.feature_network()` 的 `sqrt(2 × (1 − |r|))`，因此完全正相关和负相关均为零距离；
Euclidean 是原值欧氏距离，不暗中标准化。网页拒绝非有限输入、Pearson 常量列、全部零距离和少于三个特征；
不沿用旧绘图辅助将未定义相关距离置零的回退。每点是特征，不能与细胞降维或相关阈值网络混同，也不能推断分子鉴定关系。
选择精确 ID、输入层、var 名称/类别列；空白/缺失名称回退 ID、重名由 ID 区分，缺失类别独立显示。
为限制平方级距离/导出开销，最多 500 特征且输入数值不超过 200 万；超限先明确缩小特征集，不自动抽样。
保存完整距离表、坐标/名称/类别表及有效 UMAP 参数；固定 seed、随机初始化、单作业便于同环境重现，不承诺不同依赖版本逐位相同。

“采集稳定性 QC”将 Notebook 的参考特征分箱检查接入网页：明确选择来源列、精确参考特征 ID、强度层、
时间坐标及其含义（采集秒数、0–1 归一化时间、伪时间或当前存储顺序）；不从行号推断采集时间。
统一等宽时间箱显示参考强度箱图与逐来源细胞数，来源按首次出现顺序保留；最大坐标纳入最后一箱。
非有限坐标细胞不参与分箱及来源谱，但完整细胞表保留排除标记和 bin=0；空窗口计数为 0、强度为缺失。
参考强度保留零值、忽略非有限值作中位数；存在非有限强度的细胞总量记为缺失，不将部分和冒充完整总量。
另计算各来源在所有有限坐标细胞中的逐特征中位谱，再跨特征算来源间 Pearson 相关；
常量谱、少于两个可比较特征或没有有限时间细胞的来源显示未定义，不置零。
全体窗口/细胞表、来源中位谱与相关表随图导出和保存重开；修改所用时间/来源列或变换矩阵使图失效。
上限为 100 个来源、100 个窗口和 200 万输入矩阵数值；超限需显式取子集，不自动抽样。
这些描述不等同于生物重复验证，不证明批次消除、信号鉴定或归一化有效。

当前数据 QC PDF 汇总当前 X 的细胞数/特征数、零值比例、来源细胞数、总强度/检出特征中位数及 40 箱分布，
并列出已有参考强度元数据摘要，不重新提取或最近质量匹配。输入和参考强度须可作有限数值汇总。
当前分析报告 ZIP 在该 PDF 摘要外保留完整 QC、处理历史、已有有效差异/Marker/网络/监督/SHAP 数值和参数，
以及当前嵌入、身份匹配图的 JSON/完整作图表；不运行缺少的分析，不序列化模型或个人 AI 内容。
PDF 分页、表头重复、中文使用 STSong-Light CID 字体；长历史、长结果和大量来源的摘要上限明确标注，附件不按摘要截断。
请求必须匹配当前数据 token；重开、变换或其他数据修订后旧请求拒绝，不能把旧快照/报告当作当前结果。
身份不能核实的旧图列入省略原因，旧只读报告本来未保留的中间数据不重算补造；论文图仍由逐图导出提供。
报告不等同于保存项目、实验准确率验收、细胞级独立验证或鉴定证明。

网页监督分析的“验证方式”默认要求独立来源字段；选择细胞级探索后可不按来源分组。
监督分析按所选独立样本列划分训练/测试和 CV；不选时是细胞级划分，可能存在泄漏。
全数据插补/选特征引入的泄漏不能靠分组划分自动补救。潜变量仅对 PLS-DA 和支持 transform 的
LDA 开放；lsqr 仍可做分类。未标注细胞的潜变量为 NaN，额外保存 train/test/unlabeled 标识。
AP 不标为梯形 PR AUC，Brier 宏平均定义和校准诊断说明见 [概率诊断](#监督模型与概率诊断)。

监督训练在拟合前检查来源组支持：分组留出再加至少两折 CV，要求每个类别至少出现于 3 个来源组；
空白来源标签报错。这个下限只是划分的必要条件，不证明生物重复充足，也不保证当前 seed、test_size 和 cv
能让训练、留出与每折均含全部类别；既有划分检查继续执行，不静默改 seed 或改为细胞级验证。
选“细胞级探索”可按现有规则训练，但报告明确标记不能解释为独立来源验证。
来源组数仅计数用户选定分组列的不同值，不自动把文件、subject、sample 等字段认定为生物重复。

诊断的 `validation_audit` 同时保存全部/训练/留出及逐 CV 折的各类细胞数和来源组数，
未标注而排除的细胞计数、输入层与强度来源、可读取的预处理步骤及解释提示；不分组时来源组数为缺失值。
记录中的插补、筛选、离群剔除及部分依赖全体数据的归一化会提示核对上游泄漏。
历史可能含其他层或已恢复步骤，报告不把所有步骤断言为所选输入的变换；切换强度层不能恢复已筛除的轴。
历史缺失/无法解析和未知强度来源不能证明没有泄漏。当前不自动重做折内插补/选特征，也不追踪所有外部调参；
反复查看留出集或据此调参后，不能再将其当作独立测试。网页直接显示提示，保存重载和 JSON 下载保留完整解释。

SHAP 复用已训练模型及其训练折拟合的预处理：背景抽自训练集、解释样本抽自测试集，
可通过 `shap_background`/`shap_samples` 调整上限，种子沿用 `random_state`。
显示与导出跨样本（多输出时再跨类别）的平均绝对 SHAP；网页图的显示数量可调（默认 20 项），CSV 包含全部特征。
这不是效应方向或因果贡献，不同模型输出空间的 SHAP 数值不能直接横向比较。
网页更改模型参数会失效旧诊断；成功重新训练会替换模型并清空解释。直接 API/工作台训练失败保留原有效模型与解释。
只改 SHAP 计算参数会清空解释但保留模型；类别/细胞/特征/显示数量属于绘图设置，不重新计算解释。
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

监督模型逐字段默认值与组合限制见[监督模型高级参数](parameters.md#监督模型高级参数)。新报告保留请求值和展开默认值后的实际模型参数；PLS 另记录全训练集及各 CV 折实际潜变量数，含 SMOTE 后的训练数量限制。

## 独立原始信号诊断

原始页的“独立原始信号诊断”仅检查原始扫描，明确选择 TIC 或指定 1–8 个离子的 EIC，以及零基线或逐通道扫描中位基线。
EIC 按各参考离子的 ppm 窗口累加强度，窗口重叠时通道可以共享峰，不当作独立特征。
按原扫描顺序计算，RT 仅用于范围筛选和显示；不插值成等时间序列。中位窗口由用户填写奇数扫描数，边界使用 reflect。

设原始信号为 S、所选基线为 B，现有 `peak_recon` 计算非负峰 C 和逐通道迭代噪声估计。
重构为 B+C，残差为 S-B-C；导出另列残差总体标准差（ddof=0），与算法估计的 sigma 分别报告。
这两者都不是当前提取 SNR、空白对照或置信区间；没有自动识别细胞，也不修改项目提取参数或矩阵。
`r1_decomposition` 对 S-B 运行既有全一向量初始化的交替秩一近似，输出 a@b.T 及对应残差；
它不是 SVD 或全局最优/收敛证书，初始化可在抵消输入上退化，单通道结果不提供多通道结构证据。

每次最多 20000 个扫描、8 个通道；超限要求缩小 RT，不能静默裁剪。输入须有限；单扫描、空选择、过大强度拒绝。
迭代在冻结的有限数值上执行，不持工作区锁；返回前复核当前工作区修订、样本和原始文件身份，变化时拒绝旧结果。成功时仅提交项目视图并递增工作区修订、标记待保存；科学矩阵与提取参数保持原值。
图的完整数值附件保留扫描索引/RT/通道、信号/基线/重构/两类残差和噪声，并记录输入身份及全部生效参数。
最近成功诊断的参数和只读图随主动保存项目保留；原始文件不复制，重新计算仍须重新打开原始输入。

相关网络的新项目报告保留完整相关矩阵、节点和边，重开可重绘只读图；旧报告未存相关矩阵时不补算。监督模型重新训练使全部 SHAP 图变体失效，已有可证明字段依赖的只读解释不因无关批次编辑被删除。保存格式见[报告目录](data-output.md#统计与监督报告目录)。

### 作图子集的解释

热图筛选发生在聚合、标准分与聚类之前；不同作图范围的行标准分和排序不能当作同一固定数值尺度直接比较。
嵌入图筛选保留已有坐标和解释率，小提琴筛选不重算原比较的检验与全局 FDR。
双特征回归描述所选有限细胞范围；筛选后的拟合变化不是原统计结果被重新估计。
操作与导出见[论文图、细胞联动与热图](workflow.md#论文图细胞联动与热图)，
上游事件与保留特征的方法见[细胞事件与特征峰确认流程](cell-feature-identification.md)。
