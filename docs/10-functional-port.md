# scMM-new 功能移植记录

来源：未跟踪的 `scMM-new/` 源码快照；用户指定共同基点
`e0357ac3833e0fa5a00e93944ff0a9ef9d5f6485`，移植前 develop 为 `e983aef`。
按功能移植，保留当前目录存储、CLI、Panel 后台任务及轨迹分析接口。
不将来源快照打包或提交为正式模块。

## 阶段 1：保持算法的内存优化

- 对齐直接写入原始特征顺序，支持可复用 float32 `out` 缓冲区。
- `find_cell_peaks(feature_block_size=...)` 分块处理，保留旧强度、窗口、
  基线统计和零比例过滤语义。自定义基线滤波器仍须沿各特征的帧轴独立工作。
- 数据集预处理默认每块 256 特征；只有 debug hook 请求时保留完整基线。
  底层 `find_cell_peaks` 的默认调用及完整基线返回保持兼容。
- 分块模式逐块执行，`n_jobs` 仅用于旧的非分块路径。
- 验证：无序目标、空匹配、sum/max、缓冲区复用；三种基线统计和三种
  分块尺寸与旧算法逐元素比较。真实文件的峰值 RSS 尚未测量。

## 阶段 2：独立分析

- 新增 `scMM.analysis`：差异检验、BH-FDR、非原位 marker 分析、按文件 QC PDF、
  LDA/PLS-DA/逻辑回归/随机森林、ROC 和可选 SHAP/SMOTE。
- `SupervisedAnalyzer(..., group_key="sample")` 支持样本组互斥的 holdout 和 CV；
  无效分折、非有限输入和 SMOTE 小样本明确失败，不用 NaN 隐藏训练失败。
  上游全数据插补/特征筛选仍可能泄漏，需在用户自己的训练流程中控制。
- 扩展现有 PlotEngine，保留轨迹方法和方法链，加入 KMeans/DBSCAN/层次聚类；
  新聚类的 QC 不把 DBSCAN 噪声算作簇。
- 差异检验要求非负丰度，以细胞为统计单位；生物重复推断需先按重复汇总。
- 新依赖通过 `supervised` extra 声明；绘图仍使用 `plot` extra。
- 验证：分析、绘图与轨迹相关测试 26 项通过（警告视为错误）。

## 阶段 3：显式选择的新处理算法

- 原 `load_from_filelist` 默认仍为 `processing_strategy="legacy"`；选择 `shared`
  或 `independent` 才逐文件提取细胞。新入口 `load_from_directory` 默认 shared。
- 逐文件基线和零比例过滤的范围与旧算法不同，不能承诺数值等价。
  independent 以递增 m/z、运行中位数和 ppm 合并，同文件碰撞取最大值。
- `extraction_method="snr_v1"` 启用扣基线丰度和背景标准差 SNR；
  `reference_mz=[...]`、`reference_mode` 控制参考组合。参考离子需落在
  `reference_ppm_tol` 内。`feature_snr_threshold` 与旧 `peak_snr` 含义不同。
- 保留参考强度/比值、帧编号、来源、采集时间及算法参数；SNR 保存为
  数据集的 `feature_snr` 表，下一阶段提供持久化和 H5AD layer 映射。
- RAW 支持文件/目录，转换使用临时空间，两遍 shared 流程仅转换一次；
  保留当前 XML 完整性检查，拒绝已有或不对应的转换输出，设置转换超时。
- CLI 保持 `scmm-process` 兼容，新增策略、参考、SNR、MSConvert 参数。
- 验证覆盖真实 mzML 读取与跨文件事件边界（选峰在此测试中固定以隔离边界行为）、
  多参考组合、扣基线数值、ppm 合并和转换输出错误；未运行厂商 RAW 转换。
- 阶段完整回归：174 项通过，警告视为错误；源码 lint 通过。

## 后续阶段

4. H5AD 互操作及旧数据兼容；保留现有数据类和界面架构，记录迁移边界。
