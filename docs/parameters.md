# 参数默认值、含义与推荐

[返回文档索引](README.md) · [Notebook 工作流](workflow.md)

本页集中维护默认值、单位和参数含义，区分四类入口；操作顺序见 [工作流程](workflow.md)，调用示例见 [API](python-api.md)。

- **Notebook 默认值**：`scMM_workflow.ipynb` 顶部参数单元中的值。
- **Python API 默认值**：函数签名中的值。
- **CLI 默认值**：`uv run --locked scmm-process --help` 显示的值。
- **网页默认值**：应用层默认配置与全局预设；项目/样本已保存值及手工应用参数另有优先级。

推荐值是起始范围，不是仪器或实验的通用最优值。最终参数应由标准品、空白、批内质控和已知
参考离子验证。

Vue 网页的“参数参考”从 `/api/v1/configuration` 读取同一应用层的新项目默认值和中文帮助，
并列展示当前项目已有参数；该页面只读，不应用新默认值或追溯覆盖旧项目。
“原始谱与参数”页可编辑完整提取参数，显式应用为项目默认或样本例外；显示范围独立于提取范围。
Vue 使用应用层参数定义和新项目默认值，分析保留现有算法及固定聚类参数限制，
具体操作见[Vue 操作](workflow.md#vue-网页项目与样本)。

## Notebook：路径与运行控制

| 参数 | 默认值 | 含义 | 推荐与注意事项 |
|---|---:|---|---|
| `INPUT_PATH` | `data/example.mzML` | 原始文件、原始目录或已处理目录 | 必须修改；建议使用项目根目录下的相对路径或明确的绝对路径 |
| `INPUT_KIND` | `auto` | 输入类型 | 通常保持 `auto`；目录同时含 `.meta` 和原始谱时会识别为 `processed` |
| `OUTPUT_ROOT` | `results` | 数据、候选注释等输出的根目录 | 不要指向原始数据目录 |
| `FIGURE_DIR` | `OUTPUT_ROOT/figures` | 所有 SVG 图目录 | 多组参数比较时建议使用不同子目录 |
| `OVERWRITE` | `False` | 是否允许写入已存在的同名结果目录 | 调参阶段确认旧结果可替换后才设为 `True` |
| `LOG_LEVEL` | `INFO` | Python 日志级别 | 排错时使用 `DEBUG`；常规批处理使用 `INFO` |

## 原始谱与细胞检测

这些参数用于原始 mzML/mzXML 和 Thermo profile RAW 的提取；RAW 的额外依赖见 [安装说明](installation.md#thermo-raw-额外依赖)。

| Notebook 参数 | API 参数 | 默认值 | 含义 | 推荐与调优方向 |
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
| `PEAK_SNR` | `peak_snr` | `3.0` | 单个细胞事件内特征峰相对基线的阈值 | 2–5 可作为调试范围；越低矩阵越密但噪声越多 |
| `BASELINE_FILTER_SIZE` | `baseline_filter_size` | `50` | 沿扫描帧方向估计基线的中值滤波窗口 | 应明显宽于单个细胞事件；慢漂移可增大，快速基线变化可减小 |
| `MAX_ZERO_FRAC` | `max_zero_frac` | `0.90` | 允许特征为零的最大细胞比例 | `0.90` 表示至少约 10% 细胞检出；探索稀有特征时可升至 0.95–0.99 |
| `N_JOBS` | `n_jobs` | Notebook `-1`；目录 API `None` | 多文件或部分特征处理的并行工作数 | legacy 目录 API 自动选择 RAW=1/XML=全部 CPU；`-1` 显式使用全部 CPU；网页默认值另见下节 |

### 合并谱底层去噪参数

高层加载接口只直接暴露 `ms_peak_snr_threshold`。需要底层控制时可调用
`scMM.util.peak.filter_spectrum`：

| 参数 | API 默认值 | 含义 | 推荐 |
|---|---:|---|---|
| `baseline_window` | `101` | 局部基线窗口，偶数会自动调整为奇数 | 覆盖数个峰宽，不能小到跟随峰顶 |
| `noise_window` | `101` | 用 MAD 估计局部噪声的窗口 | 通常与基线窗口相近 |
| `baseline_quantile` | `0.1` | 窗口内作为基线的分位数 | 0.05–0.2；峰密集时使用较低值 |
| `snr_threshold` | `3.0` | 保留信号的 SNR | 高层处理会传入 Notebook 的 `MS_PEAK_SNR=10.0` |
| `keep_negative` | `False` | 是否保留扣基线后的负值 | 强度矩阵通常保持 `False` |
| `baseline_stride` | `10` | 间隔多少点计算一次基线锚点 | 增大可提速，过大可能忽略快速基线变化 |

## 数据变换

### 去同位素

此节描述 Python/Notebook 原有跨细胞回归去同位素接口。网页采用数据库分子式天然分布标记，
保留全部峰和候选，其参数见[网页注释与同位素](#网页注释与同位素)。两种算法和处理语义不同。

Notebook 默认 `RUN_DEISOTOPE=False`；开启后使用 `DEISOTOPE_OPTIONS`。API 方法
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

Notebook 默认关闭，开启后调用 scikit-learn `IsolationForest`：

```python
RUN_OUTLIER_REMOVAL = True
OUTLIER_OPTIONS = dict(contamination="auto", random_state=42)
```

- `contamination="auto"` 让算法使用内置阈值；已知异常比例时可设 0–0.5 之间的小数。
- 始终固定 `random_state` 以保证可重复。
- 先查看 PCA/UMAP 和质控指标，再决定是否删除异常细胞。

### 缺失值填补

| Notebook 参数 | 默认值 | 选项 | 推荐 |
|---|---:|---|---|
| `IMPUTE_METHOD` | `None` | `knn`、`mean`、`median`、`most_frequent` | 默认不填补；确认 0 表示缺失而非真实低信号后再开启 |
| `IMPUTE_OPTIONS` | `n_neighbors=5` | 传给相应 scikit-learn imputer | KNN 可从 5 开始；细胞少时不得超过有效样本规模 |

API 默认是 `impute(method="knn", missing_values=0)`。所有方法都会修改当前对象，并保留原行列索引。

### 归一化

Notebook 和 API 的默认方法都是 `total`；Notebook 默认额外传入 `scale=1.0`。

| 方法 | 主要参数及默认值 | 含义 | 使用建议 |
|---|---|---|---|
| `total` | `scale=1.0` | 每个细胞除以行总强度再乘 scale | 单细胞总信号差异明显时的首选起点 |
| `max` | `axis=1` | 除以每个细胞最大值 | 由稳定强峰主导且关心相对峰型时使用 |
| `quantile` | 无 | 使每个特征列具有共同分位数分布 | 假设多数特征分布相近；可能削弱真实全局差异 |
| `pqn` | `reference="median"` | 概率商归一化 | 代谢组常用；也可用 `mean` 或自定义一维参考谱 |
| `zscore` | `axis=0` | 按特征做标准化 | 适合降维/聚类，不再保留原始强度尺度 |
| `log` | `pseudo=1e-6` | 计算 `log1p(X+pseudo)` | 压缩高强度长尾；通常应在尺度归一化后单独评估 |
| `minmax` | `axis=0` | 每个特征缩放到 0–1 | 适合部分机器学习输入，不适合解释绝对倍数 |

注意：当前接口一次只执行一种方法。若需要“总量归一化后再 log”，必须连续调用两次，并记录顺序。

默认方向与零值处理细节（Vue 选项使用相同实现）：

| 选项 | 方向与默认计算 | 影响 |
|---|---|---|
| `total` | 每个细胞除以自身强度之和，默认 scale=1 | 非零总和约为 1，全零细胞保持 0；允许浮点误差 |
| `max` | 每个细胞除以自身最大强度 | 最大值为 1，总和不固定；零最大值按除数 1 处理 |
| `pqn` | 各特征跨细胞的中位数形成参考谱，细胞相对参考谱的商的中位数作为除数 | 商的中位数包含零值；参考值及除数为 0 时按 1 处理，不自动先做 total |
| `zscore` | 每个特征跨细胞减均值、除以总体标准差（ddof=0） | 产生负值，常量列变为 0；正值计数不再是原始检出数量 |
| `log` | 逐元素 `ln(1 + X + 1e-6)` | 自然对数，零值变成约 1e-6 的正数；影响后续 >0 计数和零值插补 |
| `minmax` | 每个特征跨细胞缩放到 [0,1] | 常量列为 0，原有正值可能变成 0，总和不固定 |
| `quantile` | 按特征列排序，同一排名替换为各列该排名的平均值 | 统一特征列的分位数分布，并非按细胞行归一化，总和不固定 |

## SDF 注释

此节描述 Python/Notebook 原接口；网页的完整候选、规则与天然同位素参数见[网页注释与同位素](#网页注释与同位素)。

| Notebook 参数 | API 参数 | 默认值 | 含义与推荐 |
|---|---|---:|---|
| `SDF_PATH` | `sdf_path` | `None` / API 必填 | LIPID MAPS 风格 SDF；`None` 关闭注释 |
| `ANNOTATION_PPM` | `ppm_tol` | `5.0` / API 必填 | 候选理论 m/z 容差；校准良好时 3–5 ppm |
| `ION_MODE` | `search_mode` | `pos` | `pos`、`neg` 或 `both`；应与采集模式一致 |
| `MAX_ANNOTATIONS_PER_MZ` | `max_results_per_mz` | `5` / API `None` | 每个 m/z 最多保留候选数；探索时可增加 |

自定义加合物可通过 API 的 `adducts_pos`、`adducts_neg` 传入。候选按绝对 ppm 误差排序。

## 网页注释与同位素

第四步“注释与同位素”使用本地 LMSD SDF，保留所有容差内候选，不限制最近候选数。
正模式支持 `[M+H]+`、`[M+Na]+`、`[M+K]+`、`[M+NH4]+`；负模式支持 `[M-H]-`、
`[M+Cl]-`、`[M+HCOO]-`、`[M+OAc]-`。均为单电荷天然丰度模型，不包含示踪、多电荷或源内碎片。
极性和所选加合物需与实验一致；`both` 搜索两组候选，不推断实际采集极性。
网页从元素质量与电子质量计算离子质量，甲酸/乙酸加合物按实际原子组成计算；不沿用旧 API 的近似加合物常量。

| 参数 | 网页默认值 | 含义 |
|---|---:|---|
| `annotation_ppm` | `10` | 实测与理论离子 m/z 的绝对相对误差上限；保留全部命中 |
| `isotope_ppm` | `10` | 预测同位素与观测特征的 m/z 匹配容差 |
| `max_isotope_order` | `3` | 检查 M+1～M+3；可选 1～10 |
| `isotope_tolerance` | `0.2` | 实测/理论强度比例的双侧相对容差；0.2 为理论比例的 80%～120% |
| `min_valid_cells` | `20` | 每样本最少有效细胞对数；母峰 >0、子峰 ≥0、双方有限，子峰零值参与统计 |
| `intensity_layer` | 项目的预处理输入层 | 使用未归一化、未插补强度；可显式选择 `X` 或其他层，已知变换层和 SNR 层拒绝使用 |
| `resolution` | 当前项目参数值，使用前核对 | m/z 200 处的分辨率，沿已有提取的质量缩放定义估计理论细结构合峰；必填正数 |

导入 H5AD 的输入层不保证就是原始强度，需按数据来源核对。比例按样本的有效细胞总强度比计算；
优先使用稳定 `sample_id`，否则使用 `sample`/`source_file`；没有分组字段时标为单样本。
样本间一致性、母峰未检出而子峰检出的数量均可审阅，不增加自动删除/强制保留门禁。
自动标记按每条候选关系和每个样本分别记录；显示/导出隐藏同位素时，默认使用任一样本命中且未被人工否定的关系，
也可只使用人工接受关系。评分不改变这些计算证据。

`ppm_error = (observed_mz - theoretical_mz) / theoretical_mz * 1e6`；正数表示实测偏高，
`abs_ppm_error` 取其绝对值。排序先按 `≤2`、`>2 且 ≤5`、`>5` 三档，再按类别分＋加合物分降序；
分档使用完整精度，同档同分保留并列，不再按更细的误差差异择优。未导入规则时同档候选未评分。

### 评分规则文件

默认提供 PBMC、人癌细胞、小鼠癌细胞、藻类、大肠杆菌五份可选规则预设，须主动选择并应用。JSON 根对象包含 `schema_version: 1`、可选 `name` 和 `rules` 列表。
每条规则字段为 `kind,level,value,polarity,adduct,score`；未知字段、非有限分值、重复条件和极性冲突拒绝导入。
`kind=class` 指定类别分；`kind=adduct` 指定加合物分，可用类别条件限定。
类别 `level` 支持 `CATEGORY`、`MAIN_CLASS`、`SUB_CLASS`、`LIPID_CLASS`；`value` 使用数据库类别名称/代码，
或缩写中的类别如 PC。较具体层级覆盖同一评分项的通用规则，不重复累加；同层级优先极性明确的规则，
同样具体的多个别名条件按文件中先出现者，评分证据列记录实际采用项。空 `polarity` 适用两种极性。

以下仅演示格式，分值需自行修改；它不是内置预设：

```json
{
  "schema_version": 1,
  "name": "自定义示例",
  "rules": [
    {"kind": "class", "level": "MAIN_CLASS", "value": "GP01", "polarity": "pos", "score": 10},
    {"kind": "adduct", "level": "LIPID_CLASS", "value": "PC", "polarity": "pos", "adduct": "[M+H]+", "score": 5}
  ]
}
```

CSV 表头和对应示例：

```csv
kind,level,value,polarity,adduct,score
class,MAIN_CLASS,GP01,pos,,10
adduct,LIPID_CLASS,PC,pos,[M+H]+,5
```

导入先校验并预览，点击应用排序或运行后才成为该版本的规则。命名预设主动保存，拒绝同名覆盖；
全局预设不追溯更改既有版本。正负模式的规则可保存在同一文件中，模板不包含评分项。

供人工审阅的 PBMC、人癌细胞、小鼠癌细胞、藻类及大肠杆菌草案位于
[规则文件夹](../rules/lipids/README.md)，附完整分值和原始研究依据。它们随安装包提供，新环境无需手动导入；
须主动选择预设或导入文件、预览及应用；同名用户预设优先保留保存值。分值是排序建议，不能解释为丰度或鉴定概率。

## Notebook：分析参数

| 参数 | 默认值 | 含义 | 推荐与限制 |
|---|---:|---|---|
| `EXPORT_SUMMED_SPECTRUM` | `False` | 为原始目录输出总谱 mzML | 只在检查公共峰或归档时开启，增加一次完整汇总计算 |
| `RUN_EMBEDDING` | `True` | 运行 PCA 和 UMAP | 聚类、轨迹和比值 UMAP 图依赖它 |
| `PCA_COMPONENTS` | `50` | 请求的主成分数 | 实际自动截断到 `min(细胞数, 特征数)`；常用 20–100 |
| `UMAP_NEIGHBORS` | `15` | UMAP 近邻数 | 10–30 强调局部结构，较大值强调全局连续性；必须小于细胞数 |
| `UMAP_MIN_DIST` | `0.7` | UMAP 最小距离 | 0.1 产生紧凑簇；0.5–0.8 更适合观察连续轨迹 |
| `RANDOM_STATE` | `42` | PCA/UMAP 随机种子 | 固定以保证复现 |
| `RUN_CLUSTERING` | `False` | 是否进行细胞聚类 | 先检查 UMAP 和批次效应后开启 |
| `CLUSTER_METHOD` | `leiden` | `leiden` 或 `louvain` | Leiden 通常是首选；两者依赖不同可选包 |
| `CLUSTER_RESOLUTION` | `1.0` | 社区划分分辨率 | 0.2–2.0 调试；越高通常簇越多 |
| `PARAMETERIZATION_KEY` | `time` | 时间/伪时间所在的 `obs` 列 | 原始处理自动创建 `time`；自定义真实时间需先写入 `peak_meta` |
| `RUN_TRAJECTORY` | `True` | 在 UMAP 上做滑动窗口轨迹 | 需要 UMAP 和有限的参数化列 |
| `RUN_METABOLIC_VELOCITY` | `False` | 计算局部特征变化率及总体速度 | 参数化列必须有变化；至少两个细胞 |
| `RUN_METABOLITE_TRENDS` | `True` | 计算特征随时间的池化趋势与显著性 | 大数据可能耗时；默认绘制排名靠前特征 |
| `RUN_TREND_CLUSTERING` | `False` | 对代谢趋势曲线聚类 | 需要先运行趋势分析和聚类依赖 |
| `WINDOW_SIZE` | `1000` | 每个滑动窗口的细胞数 | Notebook 会截断到总细胞数；不是秒、分钟或时间比例 |
| `STEP_SIZE` | `300` | 相邻窗口起点相隔的细胞数 | 小于窗口可形成平滑重叠；Notebook 会限制为 1 到窗口大小 |
| `PLOT_TOP_N` | `30` | 趋势热图和趋势聚类最多使用的特征数 | 20–100；注释名称为空的特征会在命名热图中跳过 |
| `RUN_STABILITY_QC` | `False` | 生成时间分箱稳定性图 | 原始数据初次质控时建议开启 |
| `TIME_BINS` | `12` | 稳定性分析时间分箱数 | 保证每箱有足够细胞；细胞少时降低 |
| `MONITOR_MZ` | `REF_MZ` | 稳定性箱线图监测离子 | 可改为内标或已知稳定代谢物；匹配最近的现有特征 |
| `RATIO_MZ` | `None` | 两个离子的比值 UMAP | 例如 `(768.5903, 774.6377)`；分母为 0 时记为 NaN |

## CLI 参数

```text
uv run --locked scmm-process INPUT OUTPUT --ref-mz REF_MZ [options]
```

| 参数 | 默认值 | 含义 |
|---|---:|---|
| `INPUT` | 必填 | 单个 mzML/mzXML/Thermo profile RAW 或原始文件目录 |
| `OUTPUT` | 必填 | 保存根目录；内部还会创建数据集名目录 |
| `--ref-mz` | 必填 | 参考离子 m/z |
| `--ppm-tol` | `10.0` | 对齐容差 ppm |
| `--resolution` | `35000.0` | m/z 200 分辨率 |
| `--mz-min` / `--mz-max` | `100.0` / `1000.0` | 正式提取 m/z 范围，包含边界 |
| `--processing-strategy` | `legacy` | `legacy`/`shared`/`independent` 目录处理策略，见 [API](python-api.md#目录处理与批处理模式) |
| `--feature-merge-ppm` | `10.0` | 独立特征轴合并容差 |
| `--extraction-method` | `legacy` | `legacy` 或 `snr_v1` 细胞提取算法 |
| `--reference-mz` / `--reference-mode` | 省略 / `union` | SNR 多参考离子及窗口 `union`/`intersection` |
| `--feature-snr` / `--noise-window` | `3.0` / `51` | SNR 特征阈值及背景噪声窗口帧数 |
| `--raw-timezone` | 环境变量或 `Asia/Shanghai` | RAW 采集时区 |
| `--cell-snr` | `5.0` | 细胞检测阈值 |
| `--cell-min-signal` | `1e5` | 每扫描参考离子最低净信号，与倍数条件同时满足；0 关闭 |
| `--peak-snr` | `3.0` | 细胞内特征检测阈值 |
| `--jobs` | 自动 | legacy 目录：含 RAW 默认 1，纯 XML 默认全部 CPU；shared/independent 仍串行 |
| `--overwrite` | 关闭 | 允许覆盖同名标准结果文件 |
| `--verbose` | 关闭 | 启用 DEBUG 日志 |

CLI 只负责原始数据预处理和保存，不执行归一化、去同位素或下游分析。需要这些步骤时使用
Notebook 或 Python API。
`--msconvert` 参数已移除；RAW 使用外部 reader 直接读取，见 [RAW 调用说明](python-api.md#thermo-profile-raw-直接读取)。

## 特征轴合并参数

`CyESIData.alignwith()` 和批处理 `concat()` 使用：

| 参数 | 默认值 | 含义 | 推荐 |
|---|---:|---|---|
| `ppm_tol` | `5.0` | 两数据集特征视为同一 m/z 的容差 | 使用质量校准表现确定，通常 3–10 ppm |
| `mz_merge_options` | `union` | `union` 保留双方未匹配峰；`ref` 只保留参考数据集特征 | 探索分析用 `union`，固定面板或严格比较用 `ref` |
| `ref_idx` | `0` | `concat()` 中作为参考轴的数据集编号 | `ref` 模式下选择质量和覆盖最可靠的数据集 |

合并会原地修改参考对象；未匹配位置填 0。批次校正不是该步骤的一部分。

## 网页默认参数

网页参数名保留英文，中文解释通过控件或预检参数名的鼠标悬停查看。预处理及分析高级参数也采用此方式；
显示位置、按钮和保存行为见[网页流程](workflow.md#网页六步项目流程)。

Vue/FastAPI 网页第二步固定使用 `snr`，取消方法选择器；内部标识仍为 `snr_v1`，用于参数、缓存和旧产物兼容。
Vue 新项目固定此方法，新参数应用、预览和新批次不接受 legacy。旧项目的 legacy 参数与产物继续可读，
表单显示 SNR 参数并提示先检查、应用；不会悄悄改写已保存参数或重算旧结果。
CLI、Python API 和 Notebook 的默认提取方法仍为 legacy；两种提取方法均支持下文的最低净信号条件。

网页首次创建项目的参考离子来自全局细胞类型预设：哺乳动物 `760.5851`（初始默认）、藻类 `734.5929`、细菌 `690.5069`。
可修改、新增预设并显式保存；项目保留自己的参数，后续修改全局预设不会覆盖旧项目。
全局预设默认写入 `~/data/results/.scmm-preferences.json`，可通过 `SCMM_PREFERENCES` 指定服务独立配置文件。

网页 `n_jobs` 默认逻辑 CPU 数的四分之一向下取整，至少为 1，且不超过进程可用 CPU 数。
首次读取原始文件时 m/z 下限向下、上限向上取整到 10 的倍数；共同特征采用各文件范围的并集，独立模式使用各文件范围。
手动应用的参数优先；自动范围不冻结其他项目默认参数。UMAP 默认 PCA 输入为 20 维，维数不足时需手动调整。

网页分析默认 `color_source=annotation`（列标签），优先选择有效 group、其次 sample；
可切换为 `feature` 或 `none`。Feature 默认 `color_sort=mean`、`color_descending=True`，即平均强度降序；
排序还支持 `total`、`median`、`detection`、`mz`、`name`。下拉选择与搜索的操作见[工作流程](workflow.md#分析显示与导出)。
火山图标签默认 FDR≤0.05、abs(log2FC)≥1，FDR 优先/效应量辅助排序，最多标注前 10 个特征；阈值、数量和排序可调整。
小提琴图每次最多 12 个，默认包含零值。它们是显示设置，不改变检验和数值导出。

用 `scmm-web --config workbench.json` 或 `SCMM_UI_CONFIG` 指定，命令行优先。

```json
{
  "processing": {
    "ref_mz": 734.5929,
    "mz_min": 100.0,
    "mz_max": 1000.0,
    "extraction_method": "snr_v1",
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

`cell_snr` 是参考信号/基线比值；legacy 的 `peak_snr` 与 snr_v1 的
`feature_snr_threshold` 含义不同。界面展开“参数含义、单位与算法差异”可查看全部解释。
手动选择“灵敏/严格”等预设会重新设置相应阈值，实际生效值以控件和任务清单为准。

### 细胞逐扫描最低净信号

网页、CLI、Python API 和 Notebook 的 `cell_min_signal` 默认均为 `1e5`，接受有限非负数。
两种提取算法均先按原有 `cell_snr` 倍数条件判断，再要求同一扫描、同一参考离子的
`I - B > cell_min_signal`，其中 I 为提取的参考离子强度，B 为滑动中位数基线。
两项都通过后才组成连续细胞窗口；净信号等于阈值不通过。0 表示关闭附加条件，保留原倍数判定。
SNR 的多个参考离子各自通过两个条件后，再按 `reference_mode` 的 union/intersection 合并。

门槛使用扣基线后的净信号，不使用原始峰高，也不在形成窗口后仅检查峰顶。
因此可以收窄弱边缘，或在中间扫描不达标时分开窗口；不额外合并窗口或设置最小峰宽。
`1e5` 是可调起点，不表示所有实验通用的检测限；应结合可信背景和真实弱细胞检查，
使用与正式提取相同的参数预览。新增判定只处理参考通道，不重新计算中位数基线。
SNR 中不通过细胞判定的扫描仍按既有规则参与背景噪声估计，因此特征 SNR 也可能随窗口改变。

新项目和直接调用使用默认值；旧网页项目若未保存此字段，打开时仅在内存中补为 0，
项目及逐样本覆盖分别处理，打开操作不写回磁盘。调整后需应用参数，保存仍由用户主动执行。
已经保存的显式值保持不变，预览复用检查包含此参数，改变后不会复用旧门槛的提取产物。

### Vue 预处理筛选说明

Vue normalization 的计算方向与零值影响见[归一化](#归一化)。选项使用同一数值实现，
每次只执行一种方法，完整说明也可在第四步问号及方法列表查看。

`min_detected` 是每个细胞至少需要的当前强度大于 0 的特征个数，低于阈值移除，等于阈值保留，
0 表示不启用此条件。先按 `min_total` 和 `min_detected` 筛选细胞，再在保留细胞中计算
`min_feature_fraction`；筛选不会重新进行峰检出或 SNR 判断。变换和插补会改变这些指标的含义。
