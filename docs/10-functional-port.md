# 上游源码功能移植工作日志

来源：未跟踪的 `scMM-new/` 源码快照；用户指定共同基点
`e0357ac3833e0fa5a00e93944ff0a9ef9d5f6485`，移植前 develop 为 `e983aef`。
按功能移植，保留当前目录存储、CLI、Panel 后台任务及轨迹分析接口。
不将来源快照打包或提交为正式模块。

后续已建立本地快照仓库，来源管理见 [上游快照](11-upstream-snapshots.md)。
版本摘要与已知问题入口见 [Changelog](../CHANGELOG.md)。以下保留此前阶段记录。
GUI 0.2.0 的来源问题与后续范围已纳入 [编号待办](12-upstream-todo.md)，
不再仅保存在忽略目录下的临时评审文件。

## 工作台完善：阶段 1（2026-09-24）

- 用户确认八页工作台、预处理 layers 历史、全局 FDR、零值仅隐藏显示、提取 m/z 范围；
  外部 JSON 默认值纳入实现。轨迹及 R2/Q2 继续暂缓，Windows 安装适配不移植。
- 进一步确认 Windows 为服务端原生路径，不新增浏览器上传；云盘允许经确认保存。
- 第一阶段实现范围参数贯通、生产/预览参数共享、单谱/多 EIC 后端和 JSON 校验。
- `.venv/bin/python -m pytest -q -W error tests/test_workbench_parameters.py tests/test_processing_application.py tests/test_optional_processing.py tests/test_extraction_preview.py tests/test_data.py tests/test_io.py tests/test_ui_processing.py`：74 项通过。
- JSON 未知键、错误类型、非法范围明确失败；兼容旧处理参数错误提示。

## GUI 0.2.0 来源移植：集成验收（2026-09-22）

- 阶段 A 提交 `db7431d`，阶段 B 提交 `f457375`；未修改 GUI、未移植暂缓的方法、
  Windows 安装启动或全局线程池补丁。没有新增依赖、修改锁文件或发布版本号。
- 集成复查将新增 preprocess 参数置于原参数之后，并增加签名回归测试，
  保留既有位置参数顺序；原默认算法与 debug hook 的完整基线行为不变。
- `.venv/bin/python -m pytest -q -W error`：209 项通过，无跳过。
- `.venv/bin/ruff check scMM tests scripts`、
  `.venv/bin/ruff format --check scMM tests scripts`、`git diff --check` 通过。
- `uv --cache-dir /tmp/scmm-uv-cache lock --check --offline` 通过。
- `uv --cache-dir /tmp/scmm-uv-cache build --offline --out-dir /tmp/scmm-port-build-20260922-final`
  完成 sdist/wheel 构建；检查均不含外部交付目录，wheel 中新 API 可导入。
- 环境排错记录：直接 pytest 入口收集 scripts 测试失败，改用仓库根目录
  `python -m pytest` 后通过，开发说明已更新。运行环境缺构建后端时非隔离构建失败，
  改用 uv 离线隔离构建成功；默认缓存只读时改用临时缓存，没有扩充项目依赖。
- 本机 Python 3.12；真实样本、厂商 RAW、Windows 和新 GUI 联调未执行，
  均在编号待办中明确保留，不能将单元测试通过当作这些验证已完成。

## GUI 0.2.0 来源移植：阶段 B（2026-09-22）

- legacy 和 snr_v1 新增 `progress_callback(value, message)`，value 为 0–1 的
  提取阶段完成比例；分块后报告，回调异常直接传播。未分块 legacy 仅报告开始/结束。
- shared/independent 将文件内进度映射到批次进度，合并成功后才报告总完成。
  worker 将提取映射到任务 10%–80%，保存/QC 完成后才写入任务完成。
  进度是阶段比例，不是耗时预测；加载和对齐仍没有细粒度进度。
- `ProcessingTask` 新增持久化 progress/progress_message，旧 JSON 缺字段时兼容默认值；
  没有改动 GUI，也未改动审核保存和输出边界。
- 新增 `RawFilePreview.cell_detection(ProcessingParameters(...), ...)`，复用缓存的
  MS1 实验及生产选峰/对齐/提取实现，返回参考轨迹、窗口、峰顶、秒制 RT 和细胞数。
  覆盖旧算法与 SNR union/intersection；不重新打开文件、不自动保存结果。
- `debug_full_baseline=False` 允许预览不保留完整基线；原有 debug hook 默认仍返回
  完整基线以维持兼容。预览仍执行完整提取，不能视为轻量抽样或实时保证。
- 验证：`.venv/bin/pytest -q -W error tests/test_extraction_preview.py tests/test_optional_processing.py tests/test_peak.py tests/test_application.py tests/test_processing_tasks.py`
  共 58 项通过；含真实解析合成 mzML 与正式提取一致、缓存不变、空细胞、数值不变、
  回调失败传播、进度单调、任务失败不误报完成及旧任务状态兼容。
- 厂商 RAW、真实大样本性能及 Windows 本轮未验证；GUI 接入明确暂缓。

## GUI 0.2.0 来源移植：阶段 A（2026-09-22）

- 来源 `snapshot/SCMM-GUI-0.2.0-source@f961809`；与旧快照 bdce317 和
  当前维护版 babc6ae 三方比较，并阅读全部 17 页 PDF。
- 按用户要求暂缓 GUI、已知有问题的方法及 Windows 安装启动，仅移植独立后端能力。
- 新增 held-out one-vs-rest PR/AP、quantile 校准曲线、每类及宏平均 Brier；
  AP 不命名为梯形积分 PR AUC，宏 Brier 明确为逐类均方误差的平均值。
- 保留既有按组 holdout/CV、SMOTE 边界检查和失败即报错；诊断不新增拟合，
  三折 CV 加 holdout 模型仍共四次 fit，不导入重复 CV 的上游实现。
- 校准曲线仅作可靠性诊断，不执行概率校准或使用 holdout 调参。
- 验证：`.venv/bin/pytest -q -W error tests/test_analysis.py tests/test_probability_diagnostics.py`
  共 11 项通过，覆盖二/多分类、分组、缺失标签、常量概率、分箱参数和未拟合调用。
- LDA/PLS-DA 潜变量写回及概率空间 R2/Q2 暂缓，后续先解决能力检查和定义问题。

## 阶段 1：保持算法的内存优化

- 对齐直接写入原始特征顺序，支持可复用 float32 `out` 缓冲区。
- `find_cell_peaks(feature_block_size=...)` 分块处理，保留旧强度、窗口、
  基线统计和零比例过滤语义。自定义基线滤波器仍须沿各特征的帧轴独立工作。
- 数据集预处理默认每块 256 特征；只有 debug hook 请求时保留完整基线。
  底层 `find_cell_peaks` 的默认调用及完整基线返回保持兼容。
- 分块模式逐块执行，`n_jobs` 仅用于旧的非分块路径。
- 验证：无序目标、空匹配、sum/max、缓冲区复用；三种基线统计和三种
  分块尺寸与旧算法逐元素比较。真实文件的峰值 RSS 尚未测量。
- 合成基准（Python 3.12，3000 帧 × 1024 特征，3 个细胞事件，n_jobs=1，
  两个独立进程）：旧路径峰值 RSS 203.6 MiB / 0.728 秒；128 特征分块
  162.9 MiB / 0.714 秒，峰值 RSS 约降低 20%，输出形状及强度总和一致。
  该测量包含解释器和输入矩阵，不能外推为真实批处理的固定节省比例。

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
- 集成阶段补齐显式相关网络和双特征散点图；保留现有特征距离嵌入接口，
  支持分类颜色和常量自变量。相关网络另需 `cluster` extra 的 networkx。
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

## 阶段 4：H5AD 互操作与兼容

- 保留当前 `CyESIData`，不改为 AnnData 子类。新增 `from_anndata`、`read_h5ad`、
  `save_h5ad`；原 `save`/`load_from_processed` 的目录格式与覆盖规则不变。
- 旧目录增加可选 `feature_snr.pkl/csv`。H5AD 使用 `layers["feature_snr"]`，
  `uns["scmm"]` 保存版本 1 的 scMM 元数据；导入的 AnnData 保留嵌入、图、
  其他层及 raw，轴子集操作同步这些对象。旧目录只保存原有表和 SNR，
  不保存全部 AnnData 分析对象；要保留这些对象请使用 H5AD。
- H5AD 默认拒绝覆盖，临时文件写完再发布；失败不会破坏已有文件。
- 异常值删除同步 SNR；去同位素 keep_parent 同步特征子集；sum 合并会使
  SNR 失效，明确移除并记录原因。旧 `alignwith` 合并会移除已失效的
  SNR/导入分析模板并记录；新顺序批处理则按定义聚合 SNR。
- 归一化与插补不会重算 SNR；该层表示原始提取时的检测证据。
- `assign_source_metadata` 按源文件名添加样本注释，默认拒绝覆盖已有字段。
- Panel 后台任务、审核保存和原始数据预览继续使用已验证的旧流程。
  新实验算法和分析目前通过 Python/CLI 使用，没有替换网页框架。
- 可选依赖实测发现原 scikit-learn 1.6 的 Array API 导入冲突；监督学习 extra
  要求 scikit-learn 1.7。锁定并验证 1.7.2 / imbalanced-learn 0.14.2 / SHAP 0.48.0，
  覆盖逻辑回归和随机森林的 SMOTE 训练与 SHAP 输出；SMOTE 前统一缩放特征。
- 增加从合成 mzML 经真实总谱选峰、SNR 提取到 H5AD 重读的端到端测试。

## 使用示例

```python
from scMM.file.data import CyESIData
from scMM.analysis import SupervisedAnalyzer, differential_features, render_quality_report

# 目录级内存优化；仍使用旧强度定义。
data = CyESIData.load_from_directory("raw", ref_mz=734.5929, feature_strategy="shared")

# 新 SNR 和多参考模式必须显式开启。
data = CyESIData.load_from_directory(
    "raw",
    ref_mz=734.5929,
    feature_strategy="independent",
    extraction_method="snr_v1",
    reference_mz=[734.5929, 760.5851],
    reference_mode="union",
    feature_snr_threshold=3.0,
    baseline_filter_size=51,
    noise_window=51,
)
data.assign_source_metadata(
    {
        "sample1.mzML": {"condition": "control", "sample": "sample1"},
        "sample2.mzML": {"condition": "treated", "sample": "sample2"},
    }
)
data.save("results")
data.save_h5ad("results/processed.h5ad")
restored = CyESIData.read_h5ad("results/processed.h5ad")
adata = restored.to_anndata()
render_quality_report(adata, "results/quality.pdf")
table = differential_features(adata, "condition", "control", "treated")

# 以下仅展示调用方式；训练和测试及每个 CV fold 都需要包含各类别，
# 因此实际实验必须有足够的独立样本，不能仅依赖上面的两个示例样本。
analyzer = SupervisedAnalyzer(adata, "condition", group_key="sample")
metrics = analyzer.evaluate("logistic", cv=3)
```

CLI 保留旧命令格式，例如：

```sh
scmm-process raw results --ref-mz 734.5929 --processing-strategy shared
scmm-process sample.raw results --ref-mz 734.5929 --msconvert /path/to/msconvert
scmm-process raw results --ref-mz 734.5929 --processing-strategy independent \
  --extraction-method snr_v1 --reference-mz 734.5929 760.5851 --feature-snr 3
uv sync --locked --extra plot --extra supervised --dev
```

## 保留的验证边界

- 实验性算法和 sequential 策略尚未用真实大批量样本评估检出率、重复性和峰值 RSS。
- MSConvert 使用模拟进程验证调用和错误处理，没有厂商 RAW 或可执行程序做真实转换。
- 默认使用旧算法；新旧参数的同名数值不能视为等效阈值。
- 差异检验以细胞为统计单位；监督分析必须明确独立样本划分和上游处理范围。
- 未移植来源快照中的 Streamlit 替换、归一化/SDF 回退或 AnnData 子类兼容问题。

## 最终验证（2026-09-21）

- 移植前完整基线 150 项通过；阶段 1 相关测试 47 项通过；阶段 2 完整回归
  169 项通过；阶段 3 完整回归 174 项通过。
- 集成后 `pytest -q -W error`：182 项通过，包含 SMOTE/SHAP 可选功能，未跳过。
- `ruff check .`、`ruff format --check .`、`git diff --check` 和离线锁文件校验通过。
- 离线构建 sdist/wheel 成功；检查两种发布包均未包含来源快照 `scMM-new`，
  从 wheel 导入新数据接口及分析模块成功。
- 当前验证环境为 Python 3.12；Python 3.11 由现有 CI 矩阵继续覆盖，
  本地未声称完成该版本测试。
