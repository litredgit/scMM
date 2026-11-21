# 主体方法插件协议 v1

scMM 在细胞提取、特征注释和统计分析的现有步骤中展示管理员启用的方法。主体提供数据选择、参数校验、工作区权限、任务、审核、项目保存和结果导出。现有离子归组、PCA、UMAP 和聚类选项属于主体。

## 可接入类型

每个实现都是 Python 可调用对象，接受下面定义的输入和已校验的参数字典。输入数据与元数据按原轴顺序传入。一个包可注册多个不同类型的方法。

| 类型 ID | 网页入口和操作 | 输入 → 返回 |
|---|---|---|
| `cell_detection` | 原始谱预览的「提取方法」，选择项目级识别方法后预览细胞窗口 | `AlignedScans`，包含已对齐 MS1 扫描 × m/z 信号和同序扫描元数据 → 有序 `CellEvent` 序列 |
| `cell_extraction` | 同处选择项目级定量方法，预览后可应用并运行批次，最后人工审核纳入 | `ExtractionInput`，包含已对齐扫描和事件 → `DataFrame`，行索引为从 0 开始的事件序号，列为原对齐轴中的唯一 m/z，强度有限且非负 |
| `annotation` | 特征注释的「插件方法」，使用页面所选测量来源，生成后进入候选审核 | `FeatureInput`，表格索引为稳定特征 ID，`mz` 为实测质量 → `AnnotationCandidate` 序列，逐条提供特征 ID、名称和理论 m/z，可附记录号、分子式和加合物 |
| `preprocessing` | 预处理的「插件方法」，选择输入层，检查影响后应用 | `MatrixInput` → 同轴、同形状的有限实数矩阵，记录来源层并将输出记为未知强度来源及其他数值空间 |
| `reduction` | 降维的「插件方法」，选矩阵、强度层或已有嵌入，填写输出名称 | `MatrixInput` → 每个观测一行且至少两列的有限实数坐标 |
| `clustering` | 聚类的「插件方法」，选矩阵、强度层或已有嵌入，填写输出名称 | `MatrixInput` → 每个观测一个整数或非空文本标签 |
| `statistics` | 差异与 Marker 的「插件方法」，按声明选择输入层和观测列 | `MatrixInput` → `StatisticalReport`，包含标准表格及可选的 Plotly 图形描述 |

### 提取和特征注释

- `AlignedScans.signal` 的列为主体完成选峰和对齐后得到的 m/z。`scans` 提供相同扫描行序的元数据，`rt` 单位为秒。`CellEvent(start, apex, stop)` 使用此行序的 0 基位置，窗口两端均包含。事件须从早到晚且互不重叠。
- 识别和定量可分别选择。只选定量插件时，主体用 `snr_v1` 识别事件。只选识别插件时，主体使用同一套 SNR 特征计算，以识别窗口之外的扫描估计背景。定量插件须声明 `intensity_definition`，由其决定强度计算和特征筛选。正式批次记录两个阶段的方法 ID、安装版本和生效参数，逐样本数值参数可另行设置。预览、正式提取和重试按原始文件身份、冻结参数和共同特征轴校验复用。
- 注释插件输出实测峰的候选。主体计算 ppm 误差、登记来源、保存候选版本并接通人工审核。需要实测 m/z 的方法可在独立特征表或离子目录的 L0 来源运行。

### 矩阵与报告

- `MatrixInput` 提供 `values`、`observation_ids`、`feature_ids`、`observations`、`observation_kind`、`source` 和 `value_space`。选用嵌入时，`feature_ids` 表示坐标维度，数值空间为 `embedding`。矩阵方法与层的选择仍受当前数据来源和分支约束。
- 预处理与统计可以定义 `observation` 参数。插件读取所声明的观测列。随机方法应将种子作为显式参数，并使用收到的种子，使相同输入下的预览、运行和复现一致。
- 输出坐标和标签使用新名称，随后可在现有页面中选择。统计表列名须唯一且非空，使用数值、文本、布尔或缺失值。图形使用英文系统文字、适用单位和可序列化的 Plotly 描述。结果按实际使用的矩阵、轴和观测列校验，重算同一方法会替换其报告。保存后可在「结果与保存」读表、查看图形和下载完整 CSV，读取只依赖项目内的数据与报告。

## 注册、版本与启用

插件安装到运行 `scmm-web` 的同一 Python 环境，通过包元数据注册入口。以下示例的入口指向模块中的 `Plugin` 对象。

```toml
[project.entry-points."scmm.methods.v1"]
lab-methods = "lab_methods:plugin"
```

```python
import pandas as pd

from scMM.plugins import Method, Plugin, StatisticalReport


def feature_means(inputs, options):
    table = pd.DataFrame(
        {"feature_id": inputs.feature_ids, "mean": inputs.values.mean(axis=0)}
    )
    return StatisticalReport(table)


plugin = Plugin((Method("feature-means", "特征均值", "statistics", feature_means),))
```

入口 ID 和方法 ID 均使用小写字母开头的小写字母、数字、连字符或下划线。示例方法的完整 ID 是 `lab-methods:feature-means`。`Plugin.api_version` 为 1，执行与溯源使用安装包的发行版本。`Parameter` 支持 `integer`、`number`、`text`、`boolean`、`choice` 和 `observation` 类型，`default=None` 表示需选择或输入。数值上下限包含端点，枚举须提供候选。方法运行前会检查未知参数、类型、取值及输入适用性。

管理员将入口 ID 加入[服务器插件配置](deployment.md#启用插件)后重启服务。插件是服务进程或 worker 信任的 Python 代码，应随服务器环境安装和审阅。重复入口、错误声明、版本不兼容或导入失败会记录到服务日志，其他已加载的能力仍可使用。已选提取方法版本变化时，网页显示保存的版本并要求重新选择。已提交的任务使用冻结版本。

相关网络、监督与 SHAP、伪时间与趋势使用各自随附的界面和计算流程，其启用配置见部署文档。此页的公共接口覆盖上表所示的主体方法。新增种类须先定义输入、输出、页面动作及保存规则，再更新协议。

## 接入验证

使用受影响阶段的小数据验证参数、结果轴、失败后原状态、保存重开和完整下载。提取方法还要核对预览、正式批次和重试的行为一致性。测试的依赖和范围声明见[分块验证](development.md#完整验证)。
