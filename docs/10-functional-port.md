# 上游源码功能移植工作日志

## 2026-09-29：Thermo RAW 阶段 3 续接

按确认方案完成 Python 单文件、目录及 CLI 入口，采集时区和流式对齐适配；
`f551542` 提交通过 296 项测试。真实文件参考离子已按用户改为 760.5847。
不部署网页、不改变科学算法，不以降精度方式改变生产 RAW；
真实结果差异和性能统一记录于 [Thermo RAW 阶段日志](16-thermo-raw.md)。
阶段 4 四条隔离进程验证完成：新旧 mzML 精确相等，RAW 量化诊断精确复现对照；
保留 float64 生产结果的实际差异，不夸大等价性。真实处理输出 307 × 622，
耗时约 94 秒、采样进程树峰值 RSS 约 685 MiB。统计报告随文档纳入 Git。

## 2026-09-29：Thermo RAW 直接读取基础阶段

完成隔离 .NET 8 C# reader、二进制管道和 NumPy 流式读取，严格 profile。
真实 wt-1 全扫描与用户提供 mzML 对照通过读取层检查：强度精确一致，m/z 差异为
32 位编码舍入；全量 283 项测试通过。按用户限额要求暂停于阶段 2，尚未切换
CyESIData/目录入口。已确认时区 Asia/Shanghai、保留 RAW float64。
提交、证据、部署位置和续接步骤见 [Thermo RAW 阶段日志](16-thermo-raw.md)。

## 2026-09-29：网页布局优化

按用户确认方案接入右侧常驻日志、小屏折叠和按类型约束的图表比例，不改变算法。
浏览器与回归证据、日志保留范围及限制见[项目式网页实施记录阶段 5](15-project-redesign.md)。

## 2026-09-28：项目式网页重设计

在独立 worktree 替换旧网页入口，不修改主仓库在线服务。阶段 1 `070b8e6` 完成项目存储和
预处理起点；阶段 2 `32368f5` 完成持久多样本提取；阶段 3 完成六步 UI、结果生命周期和保存重载。
完整回归 258 项通过（警告作为错误，无跳过），另通过 CIFS 隔离保存/回读及 Chromium 页面操作。
设计、使用方法及未覆盖的边界集中记录在[项目式网页实施记录](15-project-redesign.md)。

来源：未跟踪的 `scMM-new/` 源码快照；用户指定共同基点
`e0357ac3833e0fa5a00e93944ff0a9ef9d5f6485`，移植前 develop 为 `e983aef`。
按功能移植，保留当前目录存储、CLI、Panel 后台任务及轨迹分析接口。
不将来源快照打包或提交为正式模块。

后续已建立本地快照仓库，来源管理见 [上游快照](11-upstream-snapshots.md)。
版本摘要与已知问题入口见 [Changelog](../CHANGELOG.md)。以下保留此前阶段记录。
GUI 0.2.0 的来源问题与后续范围已纳入 [编号待办](12-upstream-todo.md)，
不再仅保存在忽略目录下的临时评审文件。

## 运行服务更新排查（2026-09-28）

- 用户反馈实际网页未改变。检查发现用户级 `scmm-ui.service` 的工作目录和虚拟环境均指向
  当前仓库，但 PID 15557 自 09-21 05:47 UTC 一直运行，早于 09-24 的工作台提交。
- 重启前通过实际 WebSocket 文档确认仍为“数据选择、原始数据预览、处理与结果”三个旧标签，
  原因是常驻进程未重新加载源码，不是浏览器缓存或错误安装路径。
- 检查两个已有持久任务均 succeeded 后，于 09-28 04:13:58 UTC 重启该 UI 服务，
  新 PID 126536；未更改服务启动参数、挂载或业务文件。
- 重启后 HTTP 200，实际 WebSocket 文档含八个工作台页面及云盘选项；服务 active/running、
  NRestarts=0。注册 Panel 模型后本次 Python WebSocket 检查成功，补齐此前连接验证。
- 未执行真实浏览器逐项操作验收；既有 `--allow-websocket-origin=*` 警告保留，
  收紧访问策略需明确实际客户端域名/IP，未擅自修改。重启操作说明已加入部署文档。

## 工作台完善：阶段 3 与集成验收（2026-09-24）

- 前两阶段分别提交 `f1ec61f`（范围与默认参数）和 `86d6d29`（数据生命周期与分析后端）。
- 接入八页 Panel 工作台、帮助/JSON 默认值、结果目录/H5AD 读取、云盘标签、历史层、
  降维/聚类、全局 FDR 火山/小提琴图、监督诊断、潜变量、审核保存和持久进度。
- 原始谱整合多 EIC、绝对索引单谱、细胞窗口和峰顶；复用缓存，正式检测参数改变后旧预览失效。
- 用户追加确认 Marker、相关网络和 SHAP 一起接入：复用既有算法，抽出独立相关网络函数，
  增加层选择、方差 Top-N、带符号边、孤立节点显示、真实 SHAP 和全部特征 CSV；
  所有结果绑定修订和参数，H5AD 保存报告，不保存可执行模型。
- 用户确认 Windows 最小兼容：缺少 fcntl 不阻断导入和分析，非 Linux 明确禁用后台任务。
  新进程模拟缺失 fcntl 验证通过；没有 Windows 实机、安装器、启动脚本或线程池补丁。
- 云盘 `/home/crs/data` 当前只读；按用户“先完成代码”未改系统挂载，保存代码完成但实际云盘发布待验收。
- 阶段后端/UI 相关测试 26 项通过，包含真实 SHAP、Marker/网络导出、H5AD 报告和参数失效。
- `.venv/bin/python -m pytest -q -W error`：245 项通过，无跳过。
  SHAP 配色模块调用 Matplotlib 的 set_bad/set_under/set_over 触发 PendingDeprecationWarning，
  在两个 SHAP 测试中按消息、类别及来源模块定向过滤；未修改全局/生产警告处理。
- `.venv/bin/ruff check scMM tests scripts`、`.venv/bin/ruff format --check scMM tests scripts`、
  `git diff --check` 和 `uv --cache-dir /tmp/scmm-uv-cache lock --check --offline` 用于集成检查。
- `uv --cache-dir /tmp/scmm-uv-cache build --offline --out-dir /tmp/scmm-workbench-build.zZIgRu`
  成功生成 sdist/wheel；没有新增依赖、锁文件变化或发布版本号变更。
- 本机服务 HTTP 返回 200；八页 Bokeh 离线构建、切换和文档序列化通过。
  Python WebSocket 客户端缺 Panel 自定义模型注册，后续诊断受工具审批服务额度限制未完成；
  已停止临时服务。不宣称真实浏览器、Windows 或云盘部署验收完成。
- 使用说明见 [工作台](13-workbench.md)，轨迹与 R2/Q2 的数值问题、含义及决策方向见
  [暂缓方法](14-deferred-methods.md)。此前日志保留为历史状态，不以旧“GUI 暂缓”描述当前功能。

## 工作台完善：阶段 2（2026-09-24）

- 新增会话数据 ID/修订号，换数据、矩阵变换、筛选等使派生结果失效，拒绝旧任务结果写回。
- 预处理按事务提交，保留原始 X 和每步 layers，记录历史；失败不改变数据，可恢复层或重置。
- 结果目录/H5AD 读取遵循存储边界；旧 pickle 目录要求明确信任，检查子文件软链接。
- 统一降维明确区分 X/obsm，记录实际参数；复用已有排除自身的 kNN 并增加重复坐标测试。
- LDA/PLS-DA 潜变量支持能力检查、缺失标签对齐、训练/测试标识与 H5AD 保存；lsqr 仍可分类，
  但不允许 transform。轨迹算法和 R2/Q2 未引入。
- 差异图仅消费完整检验表，隐藏零值仅影响展示，不对所选子集重新检验或校正。
- 后端与已有分析/轨迹回归 45 项通过；云盘当前只读挂载，按用户确认先实现代码，部署改挂载留待办。

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
