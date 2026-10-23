# 功能接入与回归契约

[任务导航](README.md) · [架构职责](development.md)

## 兼容性回归边界

以下编号用于相关修改及上游移植的回归审阅，不表示未完成缺陷：

- **REG-01**：保留 group_key holdout/CV、SMOTE 最小样本及非有限输入检查，失败必须报错。
- **REG-02**：保留旧目录兼容、H5AD raw/层/嵌入保真、原子发布和默认防覆盖，不整体替换数据容器。
- **REG-03**：保留 XML 完整性、RAW 超时/协议/资源回收、归一化零值、SDF、reference ppm 与 SNR 定义；直接 reader 失败不隐式转换。
- **REG-04**：保留 frame_id/ms_level/native_id 已验证的元数据路径。
- **REG-05**：保留持久任务、审核合并、主动保存及存储目录边界。
- **VAL-04**：holdout PR/AP、校准和 Brier 不可在反复调参后继续解释为独立测试；细胞数不等于生物重复数。

## 分析功能接入指南

本节是网页分析扩展的主要接入说明，示例全部来自已有四类分析，不增加演示算法。
先核对实际代码与分支；能力限制见[能力覆盖](development.md#前后端能力覆盖)，科学解释见[分析说明](analysis.md)。
下文 `frontend/` 相对仓库根，Python 路径带 `scMM/`。不要仅凭注册导航就声明后端能力已经接通。

### 先判断扩展类型

| 类型 | 修改位置与边界 | 验证重点 |
|---|---|---|
| 已有参数扩展 | 对应 `modules/*/*Panel.vue`；`useAnalysisSettings` 的默认值、序列化、恢复；计算参数再检查 `workflow_schemas.py` 对应模型、`parameters.py` 帮助/预设与领域函数 | 默认值、非法值、旧设置恢复、参数归属及依赖失效；纯提示修改无需重走算法流程 |
| 新图形或展示 | 模块模板、既有 `PlotView`/`DataTable`；只有新增服务端图时修改 `Plot.kind`、`PLOTS`、`analysis_plot`、`plot/workbench.py`、`PlotKind` 和结果图映射 | 绘图失败重试、展示不重算检验、保存只读图、过期图不能下载、响应式布局 |
| 完整分析能力 | 按下述领域 → 应用 → API → Vue → 保存重载与导出逐层接入；按需创建模块 | 数值、原子性、依赖生命周期、严格接口、交互、保存导出贯通 |

例如调整现有网络 `top_features` 的表单，不要求再造一个算法或导航模块；火山图的 `labels` 是展示参数，
不能因此重新跑差异检验或清除 Marker。`network` 是完整能力的现有参考。
已有 `plot/embedding.py::register_dim` 只扩展该 Python 绘图入口，**不会自动开放网页降维方法**；
网页使用 `analysis/embedding.py::reduce_dimension` 和严格的 `Reduction.method`，需要分别接通。

### 前端入口与职责

| 文件/符号（均在 `frontend/src/`） | 职责 |
|---|---|
| `features/analysis/AnalysisPage.vue` | 页面标题、公共图例/设置、宽屏导航与窄屏选择；提供页面级上下文；不放领域表单 |
| `features/analysis/registry.ts::analysisModules` | 稳定 ID、中文名称、分组、组件入口及输入要求说明 |
| `features/analysis/types.ts` | 操作/结果/图形类型、模块与传输接口、`analysisKey` |
| `features/analysis/composables/useAnalysisSettings.ts::useAnalysisSettings` | 表单默认值、`settings` 序列化、`resetSettings` 和 `restoreSettings` 旧设置兼容 |
| `features/analysis/composables/useAnalysis.ts::useAnalysis` | 草稿、项目/数据身份、摘要刷新、依赖失效、公共执行、报告与绘图；不持有矩阵/模型 |
| `features/analysis/composables/useAnalysisContext.ts::useAnalysisContext` | 模块取得页面上下文；只能在分析页下使用 |
| `features/analysis/results.ts` | `operations` 操作→结果/默认图；`resultPlots` 结果→所有关联图；`resultDownloads` 完整报告文件名，结果页复用 |
| `features/analysis/modules/{embedding,differential,network,supervised}/` | 四类真实表单、输入提示、运行按钮及图表报告布局 |
| `features/analysis/components/ResultTable.vue` | 仅显示后端仍认可的表格；复用全站 `components/DataTable.vue` |
| `stores/workspace.ts::analysisTransaction` | 整条分析执行链持有 `busy`，带工作区修订写入，核对响应身份与预期修订 |

模块按“输入与参数 → 运行操作 → 图表与报告”组织；复杂表单留在模块，高级参数折叠。
参数用英文名称，帮助用中文 `FieldLabel`/`HelpTip` 悬停展示。复用 `PlotView` 的图例、缩放和下载，
不要再实现一套格式化或图形下载；实际重复的分析报告用 `ResultTable`，不为假想复用建立万能表单。

创建面板后在 `analysisModules` 注册，现有网络条目为：

```ts
{ id: 'network', name: '相关网络', group: '探索',
  component: NetworkPanel, requires: ['matrix'] }
```

`requires` 当前是可审阅的声明，**不是自动校验引擎**。模块仍需根据 `info.layers`、`observations`、
`embeddings`、`live_results` 禁用不适用操作并说明原因，后端最终验证真实输入。
页面通过 `v-show` 保留模块状态，模块须有单个根节点；切换导航只改 `tab`，不启动计算或重绘。
现有图在模块不可见时卸载 Plotly 展示，图形描述仍在公共状态中；这不等于保存到磁盘。

网络面板使用下述现有调用方式：

```ts
const { network, store, info, execute, has, loadWithPlot } = useAnalysisContext()
// 按钮禁用条件包含 store.busy；layer 选项来自 info.value?.layers。
await execute('network', { ...network })
if (has('network')) await loadWithPlot('network', 'network_plot')
```

`execute` 负责计算→更新工作区→刷新有效结果→读取报告→绘图。独立读取用 `loadResult`，
独立重绘用 `draw`，组合读取/重绘用 `loadWithPlot`；这些都复用事务锁，不能在模块中自行拼接
多个各自释放 `busy` 的 `store.mutate/read/command`。计算失败保留先前已提交状态；成功替换的结果
清理对应旧展示，后续失败提示“计算已完成，结果已保留”，可读取/重绘。公共“重新读取分析状态”
用于恢复摘要读取；请求超时不会自动重放写操作，须先读取实际状态。

### 参数、草稿与恢复

| 所属模块 | 自有参数 | 明确共享的依赖 |
|---|---|---|
| 降维 / 聚类独立板块 | `reduction`、`usePca`、`cluster`；嵌入/着色选择 | 聚类使用独立的 `cluster.use_rep/n_neighbors/random_state` |
| 差异与 Marker | `diff`；`volcano`、`selectedFeatures`、`hideZero` 为显示状态 | Marker 使用 `diff.group_key/method/layer`，不依赖两组选择 |
| 相关网络 | `network.method/min_abs_correlation/top_features/layer` | 不依赖差异分组或后续 layer 编辑 |
| 监督与 SHAP | `train`、`validation`、`ldaSolver`、`latentKey`、`shap` | SHAP 使用 `train.random_state` 作为 seed，并依赖当前可执行监督结果 |
| 页面公共 | `legend` | 图例只改变展示，不使统计结果失效 |

恢复顺序为：清空全部表单和展示选择 → 配置默认值 → 当前项目设置（同项目草稿优先）→ 校正失效输入选择。
`restoreSettings` 对旧项目中缺失的 `train.random_state` 使用旧 `reduction.random_state`，
缺失的 `network.layer` 使用旧 `diff.layer`；迁移后分别管理。更早的 `views.settings` 字段由
`web_analysis.py::analysis_settings` 转为当前分组设置。不要因新增默认值覆盖已有项目的显式选择。

新增字段应同时检查四处：初始默认值、`settings` 输出、`restoreSettings` 的类型/缺失兼容、
`resetSettings` 的项目切换恢复；计算参数还要更新对应依赖 watcher。表单草稿放 `store.analysisDraft`，
绑定项目路径；切换项目清除草稿。切换数据身份重置面板，正常新增嵌入或修改元数据时只刷新有效性。
页面维护草稿的表单及待恢复视图按用户、工作区和项目隔离；任一身份切换清空缓存并使排队恢复失效。
读取草稿期间有新输入或工作区修订变化时，不再应用迟到草稿；延迟恢复控件同样保留用户刚输入的值。
“应用视图设置”只写内存项目设置；“保存项目”由 `store.mutate('/project/save')` 先写当前分析草稿，
再执行项目快照保存。模块不得自动保存项目。搜索/分页等临时选择不必持久化，也不应成为科学参数。

### 领域、应用与严格 API

1. **领域算法**：数值函数放 `scMM/analysis/`，需要容器能力时通过稳定门面接入。
   网络参考 `statistics.py::feature_correlation_network`；验证矩阵/layer、有限值、维度、参数范围、
   空输入和零分母。可选依赖在对应功能调用时导入并提供明确缺失提示，不增加全站启动依赖。
2. **应用编排**：`application/workbench.py::AnalysisWorkspace`承载数据 token、
   输出与溯源；现有方法为 `network`、`differential`、`train` 等。网页通过
   `web_analysis.py::AnalysisWorkflow.run_operation` 使用 `web_projects.py::project_candidate`，执行成功后一次发布。
   失败不得修改原项目；会修改已有模型的操作参考 `explain_shap` 对结果的额外深复制。
   输出嵌入/obs 键须验证合法性和冲突，参考 `reduce/cluster/save_latent`，不能覆盖已有键。
3. **严格 API**：`api/workflow_schemas.py` 增加/调整 `Controls` 子类及 `OPERATIONS`，并核对
   `Operation.operation` Literal；`options_for` 校验 options。图形对应 `Plot.kind`、`PLOTS`。
   `api/routers/analysis.py` 只处理请求和返回，不写数值计算；应用层 `ANALYSES` 也须明确允许。
   注册 Vue 或加入任意 Python 函数不会获得 HTTP 执行能力；保持禁止额外字段和操作白名单。
   `Train.model_params` 使用逐模型字段白名单和组合/训练折约束，不能作为任意函数调用入口。
4. **Vue**：补齐 `results.contract.json`、`PlotKind` 与模块；`AnalysisOperation/ResultName` 从前端显式契约的键推导，对应模块调用公共流程；
   仅新能力需要独立导航时才注册新模块。配置帮助/预设入口在 `application/parameters.py`、`preferences.py`。
5. **保存重载与导出**：`workbench.py::save_h5ad` 经 `result_catalog.py::serialize_reports` 组装 `reports_json`，
   `projects.py::ProjectStore` 管理快照和视图，`web_analysis.py::result_value/result_view/analysis_plot`
   读取实时或只读结果；`web_results.py::ResultWorkflow.download_content` 导出完整内容。
   在结果目录注册名称/关联图/元数据依赖/下载和序列化规则，同步前端显式 JSON 映射及 API 白名单；默认分页表不是完整导出。
   不保存可执行模型，不在 JSON 中舍入科学值，不把 Graph/模型塞进前端或快照。

现有操作示例：`Network` API 模型约束 threshold 0～1、top_features 1～1000；应用层只在
候选中调用 `network`；领域函数返回图和相关矩阵；网页只读边表与 Plotly 图描述，完整边表按 CSV 下载。
前端注册、API 类型和 Python 映射有意保持显式，尚无自动生成的跨语言协议或动态插件加载器。

### 输入、输出及生命周期声明

接入 PR/变更说明必须写清下表；它是审阅模板，当前没有自动读取该模板的依赖引擎。

| 声明项 | 现有示例与必须核对内容 |
|---|---|
| 输入 | 网络：当前 X 或 `network.layer`；差异：矩阵/layer + group 列和两组；降维：X/指定 obsm；监督：矩阵/layer + label/group；SHAP：实时监督模型 |
| 参数与随机性 | 参数归属、默认值、单位、范围、seed；降维/聚类记录 history，报告记录各自 parameters/分组信息；不要宣称所有结果已有统一溯源模式 |
| 输出 | 降维写 `obsm[store_key]`，聚类写 `obs[key]`；统计写 `results[name]`，监督写内存 analyzer；图写 `views.figures[kind]`；说明新键及冲突策略 |
| 依赖与失效 | 矩阵变换清下游结果；元数据仅按使用的字段清理；train 重算清 SHAP；参数编辑按对应 watcher 清结果；纯显示编辑不清统计 |
| 保存与重载 | 数据/嵌入/元数据、起点、报告与已生成只读图可保存；模型不保存；重载后 SHAP 新计算和潜变量输出须重训；网络/监督图的重载依赖已保存图，不能承诺重建任意图 |
| 导出 | 指定完整表/JSON/嵌入与图的下载方式，检查后端有效性；界面分页和格式化不能截断导出或降低精度 |

**工作区修订与数据修订不同**：`BrowserWorkspace.revision` 每次成功写入（包括绘图、设置）递增，
用于防止过时页面写入；`AnalysisWorkspace.token` 是 `(dataset_id, revision)`，表示数据身份与数据变更。
绘图不改变数据 token。新增嵌入/聚类会增加数据修订，但 `_commit(clear_derived=False)` 重绑定无关结果，
不能见到数据修订变化就删除全部展示。矩阵变换则清除派生结果。

后端有效性入口为 `AnalysisWorkspace.result`、`AnalysisWorkflow.result_value`；
`sync_sample_metadata` 和 `web_workspace.py::sync_metadata` 按依赖字段同步实时/已保存报告和图，
`result_catalog.py` 的关联图与后继结果规则清理；新增结果须补齐目录、前端契约及下游依赖。
`analysis_info.results` 用于页面可用性，`live_results` 区分可执行对象；页面隐藏按钮不能代替下载校验。
`download_content` 必须继续通过有效性入口。纯图例、标签数量、特征显示等变更不清除统计结果。

前端摘要/特征读取使用请求代次及项目/数据身份，报告和图在同一事务中核对工作区身份与预期修订。
不要在未核对身份时应用迟到的成功或错误响应。`useReadScope` 同步递增本地输入/停用代次，
覆盖同修订内 A→B→A 的选择和 KeepAlive 恢复；恢复读取放在其回调内，避免嵌套组件的激活钩子顺序使合法读取被拒绝。
恢复回调只重新读取必要摘要，不重放写入。
结果图、搜索、摘要、原始参数/预设、提取信号及保存管理各自接收当前来源的响应；草稿另按发起读取时的编辑值复核。
`readResource` 仅合并同一登录/操作代次内并发的全局元数据 GET（项目列表、全局预设），结束即移除，返回各调用者独立副本；
它不缓存科学工作区响应，不跨写操作复用旧快照。`inspect` 的可选接收谓词仅用于只读信号/计划，过期成功与错误不发布；
正式变更及已发出的前台计算仍按原工作区事务完成，不因页面停用伪装取消。
`requires` 声明和 watcher 不代替后端有效性。
现有依赖并非通用 DAG；新增依赖要显式补齐保存、重载和失效处理，不能只改前端映射。
分析仍在同步 HTTP 内完成，锁不等于后台任务、取消计算或可断线恢复的任务协议；后台化见 roadmap。

### 按风险选择接入检查

- **算法/输入变化**：小型合成数值对照、边界/非有限值、缺可选依赖、seed 重现；真实实验另记，不能以浏览器成功代替。
- **状态/输出变化**：非法输入与计算失败保留旧状态、图失败保留新结果并可重试、输出键冲突、矩阵变更清理及无关元数据保留。
- **API 变化**：额外字段/非法操作拒绝、参数类型/范围、工作区修订冲突、越权身份与候选原子性。
- **前端流程变化**：四模块切换不计算、草稿与旧设置恢复、项目/数据切换重置；重复点击、报告/绘图等待期间互斥、旧成功/旧失败响应；宽屏与 700/390px，控制台无运行错误。
- **生命周期/存储变化**：主动保存后重载报告/图、模型只读限制、旧结果与图下载拒绝；完整 CSV/JSON/H5AD 精度，分页不影响导出；依赖字段和纯展示变化分别覆盖。
- **文档**：使用行为改 `workflow.md`，默认值/单位改 `parameters.md`，科学解释改 `analysis.md`，持久化改 `data-output.md`；本节保持唯一主指南，更新 CHANGELOG/roadmap 的验证与待验收状态。

现有定位：`tests/domain/test_analysis.py`、`test_analysis_views.py` 验证算法/图；
`tests/application/test_workbench_state.py` 验证生命周期；`tests/api/test_web_api.py`、`test_web_workflow.py`
覆盖严格契约、事务、保存重载/下载；`frontend/tests/analysis.spec.ts` 覆盖设置、导航、互斥、失败重试与迟到响应，
`workflow.spec.ts` 贯通四类分析、保存重载和完整导出。共享 store 改动还要选择导航/认证/其他读请求的受影响回归。
类型/构建为 `npm --prefix frontend run build`，文档链接/锚点为
`uv run --no-sync python -m pytest tests/tooling/test_documentation.py -q -W error`。
按[分块验证](testing.md#完整验证)选择受影响检查；仅改帮助文案或已有显示参数时，不机械重跑全部算法和真实实验。

## 添加归一化方法

归一化方法通过注册表扩展：

```python
from scMM.util.normalize import register_norm


@register_norm("custom")
def norm_custom(X, params):
    scale = params.get("scale", 1.0)
    return X * scale
```

新方法应验证二维输入、零分母、NaN/Inf 和参数类型，并在 `tests/domain/test_normalize.py` 添加测试。

## 添加降维方法

轻量接口使用 `register_dim`：

```python
from scMM.plot.embedding import register_dim


@register_dim("custom")
def run_custom(X, params):
    model = CustomModel(**params)
    return model.fit_transform(X)
```

输出必须是每个细胞一行、至少两列的二维数组。


## 职责拆分约定

每次拆分说明谁拥有状态、谁验证输入、何时提交、哪些结果失效、失败后保留什么。
页面外壳组装现有控制器，子组件用 props/events；一个任务、一份表单只有一个状态所有者。
不以跨组件 watcher 同步重复状态，不在子组件重复轮询、加载配置或建立控制器。
保持公开门面、候选事务、锁次序、用户归属、修订、下载身份及恢复检查；不引入通用插件框架。

结果类型在应用登记表维护依赖、图与报告生命周期，前端显式映射通过契约检查防漂移。
训练来源记录有效 layer、seed、划分、CV、model_params 和实现版本，区分请求值与有效值；
旧报告未知字段明确保留，主动项目保存不保存可执行模型。可选依赖按功能延迟导入，
模拟缺包只证明导入边界，不能作为干净环境安装证据。
