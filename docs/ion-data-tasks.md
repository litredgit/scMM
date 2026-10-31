# 离子数据视图与应用任务卡

[主实施计划](ion-compound-plan.md) · [任务导航](README.md)

本页是待实施功能的详细任务卡，主计划的已确认范围、参数和默认决策优先。默认 L1 使用 reviewed_v1；探索自动模式独立可选。不得将任务卡记为已实现或实验验证通过。

本文件细化主计划的数据与应用契约。以下模块、签名和 schema 是建议的新契约，不代表已实现。实施时可在不改变行为契约的前提下调整文件拆分；每张任务卡完成后先做对应检查，再随主计划指定阶段本地提交；全部阶段完成后统一更新5007供用户验收。期间不重启服务，验收通过后才push/release。所有分支均属于同一个浏览器工作区，继续受现有用户隔离、工作区修订和项目磁盘修订保护。

## 已核对的现状与不可沿用的假设

- 交付代码没有 SCData/Process 类。稳定入口是 scMM/file/data.py:21 的 CyESIData；网页使用 AnalysisWorkspace（scMM/application/workbench.py:62）。
- CyESIData 的 DataFrame 列是数值 m/z；from_anndata 强制唯一正 m/z（scMM/file/_anndata_interop.py:61-80）。L2 不能伪造 m/z 来通过它。
- 新生成 var_names 是 m/z 字符串；导入 AnnData 可保留已有稳定 ID。ID 只在根数据版本内唯一，跨根必须命名空间化。
- AnnData.raw 是首次转换时的快照，可能已变换；_original 是会话完整 reset 起点，也可能已处理。二者都不能自动声明为 L0。
- layers 随 AnnData 切片裁剪，不能保留被排除特征。普通 input layer 不能充当完整 L0。
- 当前 project.json 原子发布 current/baseline/views；只支持一个活动数值分支。维护恢复把 vars(project.workspace) 编码；项目回收引用和 retention 显式遍历 current/baseline，需要同步扩展。
- 现有差异函数仅检查有限非负，再计算均值比 log2FC；正值 log1p 输入仍会通过。强度来源 raw/normalized/transformed/unknown 不足以描述数值空间。

## 总体契约：保留活动入口，每个视图拥有独立分析分支

保留 Project.workspace、saved_reports、views、saved_token、report_token 五个现有活动字段，避免改写所有领域调用。新增 Project.measurements、ion_evidence、matrix_catalog、inactive_branches。新增 scMM/application/data_views.py 为唯一切换/分支状态管理者，不允许各路由自行拼这些字段。

- 活动分支只存在于上述现有字段，不再在 inactive_branches 重复保存；非活动分支状态为普通 dict，包含 workspace 的属性 dict、saved_reports、views、saved_token、report_token。workspace 属性中只出现现有 StateCodec 已支持的 AnnData、数组、DataFrame、dict、tuple、现有允许模型类型；不能把任意对象/pickle 放进去。
- matrix_catalog 为所有视图的轻量元数据目录，包含 active_view_id。每个已物化的分析分支恰好有一个活动或非活动状态；完整源视图（特别是含结构性缺测的 L2）可以只有只读源矩阵与目录记录，尚无可计算分支。目录同时记录 active_view_id 与 active_branch_id。
- measurements 保存不可覆盖的提取/导入测量根。根的 X、obs/var 轴及提取时注释不随后续 QC、分组编辑或筛选改变；样本最新名称/组别通过现有 stable sample_id 映射覆盖到各分析分支的 obs，原始根保持历史快照。
- “L0”是一个已经明确声明来源的测量根所对应的 feature 视图，并非仪器原始谱；仪器文件仍只引用。初步 QC 是根上方的派生选择版本，不覆盖提取输出。
- 一个根允许多个 grouping run、L1 和 L2。新 run 不覆盖旧 run；新方案通过新 view_id 创建分支。新建分析时，若同一根和适用细胞范围已存在主计划定义的有效合格L1，则推荐它；没有已生成合格L1时推荐L0。生成L1或修改推荐不自动切换任何旧项目、旧分支或已有分析输入。完整源视图可拥有不可变的源矩阵；每个物化分析分支独立拥有有限 X、layers、baseline、嵌入、聚类、模型、报告与图。一个源视图允许多个具名分析分支。
- L3 只有注释/证据版本，引用 Feature 或 EC；不要求建立第四个数值矩阵。

建议函数签名（新增 data_views.py）：

```python
def initialize_catalog(project, data, *, source, origin_kind, linearity): ...
def create_feature_view(project, *, root_id, cell_ids, feature_ids, level, grouping_id=None, selection_rule=None): ...
def create_compound_view(project, *, root_id, grouping_id, quantification, cell_ids=None): ...
def freeze_active_branch(project) -> dict: ...
def preview_analysis_materialization(project, *, view_id, availability_selection) -> dict: ...
def materialize_analysis_branch(project, *, view_id, preview_identity, availability_selection, missingness_policy=None): ...
def activate_view(project, view_id: str, *, branch_id=None, expected_catalog_revision: int): ...
def iter_branch_states(project, *, include_active=True): ...
def require_view(project, view_id=None, *, require_valid=True): ...
def clone_project_views(project): ...
def validate_catalog(project, *, check_matrix_digests=True): ...
def catalog_dirty_token(project) -> tuple: ...
def resolve_analysis_input(project, *, view_id=None, branch_id=None, layer=None, purpose, variable_ids=None): ...
```

activate_view 候选顺序必须是：检查工作区修订/目录修订→冻结当前分支到候选→校验目标来源与完整状态→恢复目标到候选→一次性交换 Project 字段→递增浏览器工作区 revision。失败不修改活动视图、结果、目录或 UI。切换不重新运行算法，也不把目标 baseline 替换为切换前的数据。

现有 dataset token 可继续保持 (dataset_id, revision) 的二元 API 以兼容大量图下载协议；每个分析分支创建独立 dataset_id，并在新 input binding 中额外保存 root_id/view_id/grouping_id/quantification_id/value_semantics。不得让两个视图共享 dataset_id，即使恰好矩阵相同。

## 核心 schema（新增领域schema从1起；含catalog项目外层为2）

### MeasurementRoot

```json
{
  "id": "root_uuid", "origin_kind": "extraction|imported_feature|composite",
  "identity": "canonical_numeric_and_axes_digest", "created_at": "UTC",
  "source": {"kind": "raw_batch|h5ad|legacy|merge", "path": "authorized reference", "identity": "input digest"},
  "intensity_state": "raw|normalized|transformed|unknown",
  "value_semantics": "linear_abundance|log_abundance|standard_score|other|unknown",
  "data": "in-memory AnnData; on disk artifact object",
  "root_feature_namespace": "root_uuid", "parents": []
}
```

读取已有数据不能只靠层名、raw 名称、非负数值、reset 或保存动作宣称 linear/raw。新原始提取可以明确声明 linear/raw；旧数据维持unknown，常规分析及旧Python调用保留legacy边界；新视图严格入口不把unknown当作线性比例/FC输入。旧调用的显式legacy声明和报告不提升来源可信度，见主计划S6。历史记录能证明 log 时可降为 log，不得反向补造 raw。

### MatrixView

```json
{
  "id": "view_uuid", "name": "user text", "level": "L0|L1|L2",
  "root_id": "root_uuid", "root_identity": "digest", "parent_view_id": null,
  "grouping_id": null, "grouping_identity": null,
  "quantification_id": null, "variable_kind": "feature|empirical_compound",
  "source_matrix": null, "analysis_branches": [],
  "availability_policy": null, "materialization_identity": null,
  "selection": {"cell_ids": [], "feature_ids": [], "rule": {}, "membership_digest": "digest"},
  "lineage": {"software_version": "...", "implementation": "digest", "parameters": {}},
  "status": "valid|historical|stale", "stale_reason": null
}
```

L1 的变量继续使用所选原 feature_id，保留未知和未解决冲突；L2 变量使用 ec_id，var 可含 neutral_mass、quantifier_feature_id、quantification_status、evidence_summary，neutral_mass 可空且可重复。L2 通用显示用 EC ID/用户名称；原始谱图必须回到明确的 member feature。所有以 m/z 匹配的操作先检查 variable_kind，不能把 neutral_mass 作为 mz 自动使用。

### AnalysisBranch

```json
{
  "branch_id": "uuid", "view_id": "uuid", "source_identity": "digest",
  "materialization_selection": {"cell_ids": [], "variable_ids": [], "policy": "complete_availability"},
  "materialization_identity": "digest", "current": "AnnData or artifact",
  "baseline": "AnnData or artifact", "semantics": {}, "revision": 0,
  "saved_reports": {}, "views": {}, "runtime_dataset_id": "fresh per open"
}
```

源视图不可变，数值处理只修改分析分支；同一源可有多个独立分支。正式保存写只读报告和图，
不编码模型/训练对象；维护恢复才按现有白名单编码模型。每次正式重开为每个分支创建新运行token，
按数值/轴/依赖摘要重绑定有效报告与图并重建项目已保存标记，不能复用旧会话token。

### 关系、实体与映射

关系/归组 run 由主算法计划定义；本数据层至少强制下列外键和版本字段：

- relation: relation_id、run_id、root_id、source_feature_id、target_feature_id、relation_type、charge/adduct/isotope_order 假设、质量/强度证据、状态与冲突。
- empirical_compound: ec_id、run_id、root_id、neutral_mass hypotheses、entity_status；没有中性质量仍可保留实体，不能捏造 0。
- membership: membership_id、ec_id、feature_id、ion_identity hypothesis、role、status，允许同一 feature 出现在多个竞争性假设；不在根 var 填一个强制唯一 ec_id 取代此表。
- selection_audit: view_id、feature_id、action=keep|exclude、reason、supporting_relation_ids、representative_feature_id；每个 L1 根 feature 都能解释去向。
- quantification: quantification_id、ec_id、method、quantifier_feature_ids、fixed_selection_rule、parameters、applicability、status、reason、input semantics、implementation digest。
- compound_candidate: candidate_id、annotation_version、target_kind=feature|ec、target_id、database identity、formula/structure candidates、证据维度及适用范围。注释不是 membership 唯一性依据。

以上证据记录先规范化为严格 JSON（finite values；缺值用 null；集合排序；不允许对象任意序列化），再计算摘要；DataFrame 只用于显示/CSV。矩阵摘要使用明确dtype/shape/轴/数值字节协议；完整源L2的NaN先按约定规范化（禁止依赖不同NaN payload字节），并同时绑定availability mask与缺测原因摘要，不用非法JSON NaN编码。引用的 feature 必须属于 run 的根，view 的 grouping/quantification 必须匹配同一个根和版本。

## 任务卡 D1：根、数值语义与视图目录

建议模块：新增 scMM/ion/contracts.py（唯一schema/枚举/外键契约）与 scMM/ion/identity.py（现有 merge_sources.identity 的可复用、非循环依赖摘要实现）、scMM/application/data_views.py；扩展 projects.py Project 字段、web_projects.project_candidate/sync_metadata、project_batch.py 提取纳入入口。

步骤：

1. 将根 digest、变量类型、value_semantics 的验证做成领域辅助函数；禁止依赖 HTTP 类型。
2. 实现新提取纳入后的immutable MeasurementRoot和L0构建函数；S1～S6仅内部及隔离测试使用，S7完整用户入口才启用。原始提取文件仍保留原路径引用，不复制原始谱。
3. 完整Feature H5AD/旧结果导入创建 imported_feature 根，按显式来源填写语义；导入已有新 catalog 的项目包走单独严格读入，不把其活动矩阵误当全项目。
4. 实现 Project candidate 对活动及非活动数据的事务性复制；大对象可只读共享根，修改分支必须 copy，不得 shallow copy 后写入旧根。
5. 根处于未知/已变换来源时允许保存、浏览和常规探索，化学强度证据入口根据目的拒绝；给出错误原因，不自动改用其他层。
6. 外部样本元数据同步遍历所有分析分支的 current/baseline；根据依赖逐分支失效。根 obs 保持提取时快照。
7. catalog_dirty_token 纳入所有分支修订、证据/目录修订；Project.unsaved 不能只看活动 workspace.token。仅切换活动视图也视作需要保存的项目展示状态。

必须失败：重复 ID、无效根 digest、跨根外键、未知 schema、非法 metadata 类型、分支丢失、创建空矩阵、筛选全空、并发旧 revision、试图覆盖已有根/run/view ID；失败前后全项目状态一致。

测试：新增 tests/application/test_data_views.py、tests/domain/test_ion_identity.py；扩展 test_project_batch.py、test_workbench_state.py。identity测试主归属ion-grouping；应用注册到workbench/processing块并按真实消费者扩展（根身份变化下游包括 projects、api、annotation、plotting、time）；运行 tests/tooling/test_test_blocks.py 验证新增源覆盖。

## 任务卡 D2：L1/L2 构建与完整定量缺测契约

建议模块：在 scMM/ion/representation.py 实现（纯函数，schema导入contracts.py、摘要导入identity.py）；application/data_views.py 与主计划catalog模块负责目录/工作区安装，不复制一套schema。签名：

```python
def build_l1(root, grouping, *, selection_policy, cell_ids=None) -> tuple[AnnData, dict]: ...
def build_l2(root, grouping, *, quantification_spec, cell_ids=None) -> tuple[AnnData, dict]: ...
def validate_quantification_spec(root, grouping, spec): ...
```

步骤：

1. L1 实现选择掩码与逐 feature 审计，默认策略遵循已确认主方案并写成具名版本；仅接受被算法明确判为可排除的冗余关系，未解决 feature 保留。保留原强度，不能把选择偷偷变成求和。
2. L2 首先支持完整的固定代表离子策略（自动确定性选择+用户明确覆盖）：同一quantification_version内对一个EC固定一个feature作为quantifier，不逐细胞挑最高峰，不在某个加合物未检出时临时换另一个。
3. 自动选择只用与分组标签无关的质量/覆盖/响应等预先记录规则；相同输入得到同一选择。不得用差异 p 值或用户目标分组挑代表。本次L2只实现fixed_representative；多离子整合只预留schema扩展点，任何其他method在执行入口明确报unsupported，不能仅凭传入规则就执行加和或权重整合。
4. 无可靠定量策略的 EC 保留在 entity/quantification 表，status=not_quantifiable；默认不生成其全局 L2 列，构建报告列出排除原因和数量。EC 识别数与 L2 变量数不同。
5. 已纳入测量轴的 quantifier 未检出沿用当前 0 语义；未被测量/不可比的结构性缺测不得填 0。完整只读源 L2 作为独立 AnnData 保存 X=NaN 和同轴 layers['scmm_quantifiable'] 布尔 mask，满足 NaN 恰好对应 mask=false；inf 永远非法。它位于 source_matrix，并不直接装入 AnalysisWorkspace。
6. 同一个观测 feature 尚在竞争归属时，不把其全部强度重复分给多个 EC。相关 EC 保持 unresolved/not_quantifiable；L0/L1 保留信号，证据图可显示竞争边。
7. 保持 AnalysisWorkspace._validate 的全有限 X 契约。preview_analysis_materialization 提供严格的 complete_availability 选择预览：在用户明确选择的细胞集合上，保留所有细胞均 mask=true 的变量；或者在明确选择的变量集合上，保留所有变量均 mask=true 的细胞。用户必须明确选择“固定细胞取共同变量”或“固定变量取共同细胞”，不能交替删行列迭代猜最大完整子矩阵。预览列出保留/排除的精确ID、原因、形状和原源矩阵/目录/策略摘要。materialize_analysis_branch 复核预览身份后生成有限 AnnData，记录完整选择映射和策略；共同集为空明确失败。activate_view 遇到只有源 L2、没有可计算分支时返回 materialization_required 与预览入口，不能自动删列或补0。
8. 用户显式选择的源 L2 缺测处理只在 materialize_analysis_branch 内生成新的有限分析分支，不修改源矩阵或强迫所有算法支持 NaN。限定为已有方法能够明确解释的策略，记录源 availability mask、处理前后摘要、填补数量与方法；未支持的策略明确拒绝。原工作区 impute 继续保持“0作为缺失”的兼容语义。插补不把不可观测事实改成真实检出；默认 FC 对结构性缺测插补分支保守拒绝，除非该分析明示选择相应方法并报告假设。
9. 每个物化分析分支创建独立 current/baseline；reset 只恢复该有限分析分支的预处理起点，回到完整 L2 源矩阵使用源视图浏览/导出，不能以 reset 冒充恢复全部未量化变量。恢复 L0 用视图/分支选择；rename/annotation 不改变 baseline 数值。源 L2 的 NaN、availability mask、原变量全集不随分析分支的共同可量化子集、插补或后续筛选改变。

必须失败：未知 EC、未解析成员被重复量化、代表不属于 EC、跨根代表、代表规则不确定、缺测 mask 与 X 不符、共同可量化集合为空、预览后源/策略变化、未经预览显式选择就激活含NaN源、对数/标准化输入生成定量、非fixed_representative方法即使附带权重也拒绝、生成全空 L1/L2、未经明确缺测策略进入不支持缺测算法。必须验证原根数组逐值不变。

测试：新增 tests/domain/test_ion_representation.py；扩展 test_workbench_state.py/test_data_views.py，包含“固定 quantifier 低于另一个 adduct 时也不换离子”、同一信号竞争 EC、按 source 结构性缺测、0 vs NaN 差别、两种固定轴complete_availability策略、空共同集拒绝、预览后源修改拒绝、源矩阵与有限分支独立、构建失败事务回滚。纯领域测试主归属ion-grouping，应用及数值消费者登记workbench/analysis并按映射扩展。

## 任务卡 D3：多分支持久化、导入导出与严格兼容

建议模块：新增 scMM/application/data_view_storage.py、scMM/file/ion_bundle.py；修改 ProjectStore.open/save、saved_dataset_summary、workbench.save_h5ad、API download、matrix_export。

推荐项目磁盘布局：

```text
project.json                         # revision + active view + catalog artifact reference
snapshots/<snapshot-id>/
  catalog.json                       # 所有根、视图、run、branch、文件摘要及引用
  evidence/<run-id>.json              # 完整关系/成员/候选/定量记录
  evidence/assets/<hash>.<ext>        # 托管规范化峰表/必要附件正文
  roots/<root-id>.h5ad                # 本轮首次保存的 immutable root
  sources/<view-id>.h5ad              # 完整源L2，包括NaN与availability mask
  branches/<branch-id>/current.h5ad
  branches/<branch-id>/baseline.h5ad
  branches/<branch-id>/views.json
```

含catalog的项目外层schema_version固定为2，新reader同时支持旧1与新2；未启用新格式的旧单分支可保持1。旧reader拒绝2，不能仍用1加扩展字段导致旧版保存丢分支。为兼容当前列表/旧下载，project.json.artifacts.current/baseline/views 继续引用活动分支，同时 artifacts.data_catalog 指向 catalog.json。catalog 中的每个路径都为项目内相对路径（统一 artifact/path 字段），不可越界或经符号链接跳出。根已有完整保存 artifact 时可继续引用旧快照的根，必须把该引用作为显式依赖纳入回收保护；不做全局去重数据库，不做后台自动迁移。首次保存的所有根文件必须位于本次候选快照中。

步骤：

1. save 冻结活动分支，验证全目录和全部外键，检查现有 project disk revision，再创建候选快照。
2. 先写全部需要写入的根、完整源视图（含NaN/mask）、证据、各分支 current/baseline/views，再写 catalog；逐文件摘要/回读核对；最后原子发布 project.json。任一分支失败不得发布部分新目录。已有快照不被覆盖。
3. open 先读取全部元数据并验证路径、schema、引用完整性，构造完整 candidate；必要的数字/轴/外键摘要验证后才替换工作区。缺一个被引用分支/根即明确失败，不静默只恢复活动视图。
4. 旧 schema 项目不原地改盘：读入时映射为单一 imported_feature L0/catalog；原 current/baseline/raw 的原义保留。下一次主动保存才写新格式，保留旧快照。新显式 schema 畸形不可按旧格式降级。
5. H5AD 导出明确区分 source_view 与 analysis_branch/current/layer：source_view 导出完整源L2，保留NaN及布尔availability mask、全部原变量ID和缺测原因；analysis_branch 导出有限可计算子矩阵及其完整选择映射，不宣称含全部EC。CSV的结构性缺测留空，另导出availability.csv和缺测原因表；0仍写0；任何JSON缺值用null而非NaN。单个 H5AD 导出只代表明确所选对象；uns 放本视图根身份、完整 feature/EC 映射、量化与注释版本快照，不宣称含完整 L0。导出 L2 的名称为 EC ID，metadata 解释，不冒充离子 m/z。
6. 项目证据 ZIP/bundle 自包含所选根+views+关系+定量+候选+hash manifest；默认不含原始谱、不含可执行模型。import_bundle 先限大小/检查重复路径/禁止绝对路径、..、symlink、zip bomb，再在隔离临时目录验证；完全成功后构造候选，不执行文件内容。
7. 通用 CSV 使用 variable_id 主键，附 variable_kind/label/quantifier mapping；保留现有 MetaboAnalyst CSV 的 Sample/Label 契约，并增加 accompanying metadata CSV/JSON 下载；不可只把 compound 名称当唯一列名。
8. tagged source-L2 H5AD导入先识别标签，安装只读source及NaN/mask，预览物化后才进入有限工作区。若缺完整L0，保留root身份引用及root_available=false，禁止伪造Feature根；依赖原根的归组/原谱回溯明确不可用。完整bundle才恢复全部根与外键闭包。
9. 证据规范化峰表和必要附件正文写入受摘要校验的托管artifact；原导入路径只作来源，重开不依赖临时路径。自包含bundle包含托管正文，引用扫描遍历这些文件。
10. 正式保存逐分支调用只读报告序列化，不将StateCodec模型编码直接复用到正式快照；维护包可按白名单保留模型。
11. 项目列表只读catalog/活动h5ad头部，不为列表加载所有分支矩阵。

必须失败：第二/第三分支写失败、根回读摘要不同、catalog/schema未知、丢失基线、跨项目路径、过期 disk revision、bundle 部分损坏、重复 JSON ID/ZIP路径、超资源上限；旧 manifest 和已有工作区继续完整可用。

测试：新增 tests/application/test_data_view_storage.py、tests/domain/test_ion_bundle.py；扩展 tests/application/test_projects.py、test_saved_items.py，tests/api/test_web_workflow.py；登记 projects/data/api 块。另验证源L2 H5AD导出→导入和自包含bundle导出→导入的NaN/0/mask/全部EC ID/缺测原因往返；CSV+availability配套导出不把缺测变为0；有限分支与源矩阵的选择映射往返完全相同。增加非活动模型正式保存后仅报告可读、维护恢复后预测一致的对照；至少一次多分支保存重开后逐值比较所有 root/完整源L2（含NaN相等与mask精确相等）/current/baseline/layers、关系 ID、候选及有效报告，证明未重算。

## 任务卡 D4：所有下游分析、报告与图接入

建议模块：data_views.resolve_analysis_input、util/intensity.py、analysis/statistics.py、embedding.py、application/workbench.py、web_analysis.py、web_time.py、reporting.py、result_catalog.py、plot/workbench.py、前端 analysis/results/preprocess 相关组件。

步骤：

1. 在所有请求/报告统一接收 view_id（省略表示活动），layer 仍只表示同视图同轴数值版本；输入摘要统一包含 root/view/grouping/quantification/变量轴/细胞轴/数值语义。所有写操作继续检查浏览器 workspace revision。完整源L2可以查看/下载，但运行分析先明确物化有限分析分支；请求/报告另带branch_id，省略时指当前活动分支。
2. 活动切换后页面从目标分支恢复表单/图/结果；失效和未生成状态分别显示。非活动分支的结果不得被当前分支下载端点错误返回。
3. PCA/UMAP、聚类、差异/Marker、监督/SHAP、热图、网络、特征散点/特征嵌入、采集稳定性、时间/趋势/速度都从同一解析入口取得所选视图。每个方法保持既有领域职责；EC 图使用 EC 标签，原始 m/z 图经成员映射明确选离子。
4. 差异函数增加独立 effect_layer 与 test_layer（旧 layer 为两者一致的兼容别名，不能同时冲突指定）。effect 输入必须 linear_abundance 且满足该统计方法缺测策略；Welch/Mann-Whitney 的 test 输入明确记录数值空间。不能把 log 均值比标成原丰度 FC。默认 effect 输入从本视图预处理起点/明确线性层选择，不靠名称猜。
5. 现有 raw/normalized/transformed/unknown 保留兼容，另记录每个 X/layer 的 value_semantics、imputation、normalization、batch-correction provenance。变换函数逐项传播，恢复所选 layer 精确恢复语义，reset 恢复本视图 baseline 原义。未知来源不经重新保存升格。
6. 元数据更新：同值写回不改数值；sample_id 稳定映射所有分支；只失效依赖改动字段的统计/图。注释候选更新不重做定量，不清除纯数值 embedding；使用注释名称/类别的图、通路表根据 annotation_version/label digest 失效。
7. grouping 版本、L1选择、代表离子改变一律创建新视图，旧视图保留 historical。无法证明来源仍有效的旧运行标 stale，允许审计查看，禁止当当前结果下载；“查看历史”与“下载有效分析”状态分开。
8. 每份报告声明视图、变量含义、定量方法、排除/歧义/不可量化数、缺测/插补、预处理及检验单位。报告同时可导出根 feature 数、归组实体数、L1变量数、L2可量化变量数；这些不是鉴定成功数。
9. 图像 meta 绑定 view identity+数值结果 identity+显示所用注释摘要；重开只对证据证明不变的图 rebind。保持自动图文字英文、用户名称原样，按钮及界面提示中文。
10. 增加 L0/L1/L2 对比报告：同一用户选定细胞集合、相同算法参数和 seed 时并列矩阵维度、PCA解释方差、聚类一致性、差异 feature→EC 映射与重复命中数。UMAP 形状不作科学正确性指标；不将特征减少率当算法质量。不同数值空间/样本集合必须显示，不能悄悄补齐。
11. 本任务不借机替换整个统计框架：重复层推断仍须明确 biological replicate 字段；已有细胞级结果继续标明统计单位，不把新 EC 矩阵解释成解决伪重复。可以提供本次数据视图所需的重复汇总导出，不在此阶段新增所有混合效应/通路推断引擎。

必须失败：L1结果请求套到L2、旧view token、用标准化/log层作原丰度FC、选 feature_id 当 ec_id、过期注释图下载、不同细胞集合假装直接比较、结构性NaN默默变0。需要验证更新 L3 后纯数值结果逐值不变且新标签图正确失效。

测试：扩展 tests/domain/test_analysis.py、test_analysis_views.py、tests/application/test_workbench_state.py、test_result_catalog.py、test_time_analysis.py/test_time_trends.py/test_time_velocity.py、tests/api/test_web_workflow.py/test_time_api.py；新增 tests/application/test_view_comparison.py 和 frontend/tests/ions.spec.ts。对应 analysis/plotting/workbench/time/api/api-time/browser-workflow 块，统一登记主计划 browser-ions 块（视图选择共享组件的下游包括 browser-preprocessing/browser-analysis-journey/browser-storage/browser-lipids）。

## 任务卡 D5：合并的变量类型和证据边界

建议模块：新增 scMM/application/ion_merge.py；修改 merge_sources.py/processed_merge.py/web_merge.py/merge_audit.py，新增 strict API controls。保留原 feature m/z 合并算法与它现有歧义规则，不统一改名为 compound merge。

步骤：

1. 每个 merge source 带 root_id/view_id/variable_kind/quantification identity；preview 冻结并复核全部源分支及根身份，不只活动 data。资源上限计入所有要带入的根/关系/基线，超限明确拒绝，不能丢弃证据减到上限内。
2. feature↔feature：可复用现有 ppm 映射；生成新 composite measurement root 和 source-feature→merged-feature 多对一映射。原 run/关系/注释完整按 source namespace 存为历史证据，不把源 group ID 直接拼成新根的统一 grouping。
3. 合并后需要新的统一 L1/L2 时，针对新根重新运行已经批准的 grouping/quantification；源分支及原根仍可审计。当前/完整起点的 union/intersection 差别沿用既有明确契约，不用当前过滤后的列冒充完整根。
4. EC↔EC：不能按 neutral_mass ppm 或同一候选名称自动合并。新增显式 EC alignment map，记录 source EC、目标新 EC、匹配依据、人工/证据选择、quantifier identity/响应可比性。质量/注释只生成候选映射；未解决项保留独立源 EC 列。
5. 默认仅对已明确对齐且量化响应可比的 source EC 合并为同一列；无法说明可比性时保留分源变量和 unavailable mask，不将不同 adduct 响应静默放到同一列。跨 source 缺测保留在完整源L2的NaN/availability中，与测量中未检出0分开。根据 D2 的显式共同可量化选择或缺测处理另建有限分析分支，不把含NaN源直接交给旧工作区。
6. feature↔EC 混合源明确拒绝，指引选择共同变量层级；用户可从同源根另建所需视图再合并，不隐式改变当前选择。
7. 合并结果是新分支/新根，不覆盖 source 视图；候选构造/安装一次完成，失败保留全部旧分支。导出 mapping、冲突、定量可比性及源版本 CSV/JSON。

必须失败：同一源重复/硬链接别名、预览后任一根/非活动源改变、跨层混合、neutral_mass相等但无匹配依据、同一 source EC 映射多个目标而重复计量、响应不一致强制汇总、映射目标不存在；仅重命名不改变匹配身份。

测试：新增 tests/application/test_ion_merge.py；扩展 test_processed_merge.py、tests/api/test_merge_api.py；跨源 L2 存在相同中性质量不同 quantifier、同候选不同实体、0/NaN等用小型合成数据验证。workbench/api/browser-workflow 块。

## 任务卡 D6：维护恢复、内存边界、引用保护与回收

建议模块：data_views 统一导出/import branch state；修改 recovery.py、state_codec.py、deployment_maintenance.py、retention.py、trash.py、web_results.py、saved_catalog.py；新增 application/project_references.py 统一引用枚举，避免第三处继续只硬编码 current/baseline。

步骤：

1. 提供 export_project_state(project) / restore_project_state(payload)，明确导出 measurements/catalog/evidence/活动及非活动分支。StateCodec 只编码受支持类型，不允许按 JSON 指定任意构造器。正式保存包仍无模型，维护恢复可保留既有白名单模型规则。
2. recovery estimate 遍历所有根、完整源视图（含NaN/mask）和各分支 X/layers/raw/obs/var/uns/图/模型，按对象身份去重；新目录不能绕过 snapshot_byte_limit、磁盘/内存/时间上限。共享根只读，不能借共享引用串工作区或用户。
3. 恢复逐分支验证 source/root/view/grouping/quantifier身份、完整轴和语义；逐模型以该模型所属分支的训练矩阵验证，不拿活动L0对照非活动L2模型。恢复后的预测/拟合状态数值仍须符合现有严格校验。
4. 保留部署优先尽力暂存/恢复：坏分支使该会话恢复失败并隔离，不能只恢复看似成功部分冒充完整恢复；不阻止其他会话/生产启动。不得让新结构重新引入“等全部用户关页”要求。严格维护仍可按现有流程全部失败即不更新。
5. 恢复保持 active_view/active_branch、源L2的NaN/mask、可量化选择预览或已物化分支的精确ID、各分支未保存状态、草稿、图、目录修订；任何晚到编码不能发布本轮已超时会话的恢复指针，原有部署维护测试继续通过。
6. project_references.iter_project_artifacts(manifest, folder) 先读目录，返回所有根/完整源L2及mask/证据/各分支current/baseline/views/映射/导入source引用，校验path与schema。retention、trash、scoped_cleanup、SavedItems全使用这一入口，并遍历其他在线/非活动分支的未保存引用。
7. 引用闭包需要保护 catalog 引用旧快照内的 immutable root：即使旧快照不是最新 current，只要有根仍被当前或其他项目/未保存分支引用就不得回收。未知schema、引用文件不可读、catalog损坏、源路径身份不确定时保守阻止清理。
8. 清理计划仍可审阅、执行前复核文件身份与引用；不自动删除实验原始谱。回收恢复检查完整目录依赖，冲突不能逐文件拼接。新 export bundle 的引用语义区分自包含证据包与仍外链根的对象。

必须失败：非活动分支损坏、一个非活动模型matrix不符、跨用户owner替换、未知编码类型、部分catalog丢失、晚到指针、回收只看活动分支导致丢根、cleanup plan后新建引用；这些失败不能损坏正式项目/其他会话。

测试：扩展 tests/application/test_maintenance_recovery.py、test_retention.py、test_retention_scheduler.py、test_saved_items.py、tests/api/test_maintenance.py/test_deployment_maintenance.py；新增 tests/application/test_project_references.py。登记 projects/workbench/api 块。必须有“活动L1、非活动L0/L2且L2有训练模型”的恢复，及“新快照引用旧快照根而旧目录受保护”的回收测试。

## 生命周期精确规则表

| 事件 | 测量根/关系证据 | 视图矩阵 | 分支结果/图 |
|---|---|---|---|
| log/scale/impute/normalize | 不变 | 只变目标分支current及同轴层 | 目标分支数值结果失效，其他分支保留 |
| QC/subset/outliers | 根/完整关系不变 | 目标分支轴裁剪，保存选择与来源 | 目标分支结果失效；不能让关系外键仅因当前裁剪被删除 |
| restore layer | 不变 | 同视图当前轴上恢复layer及真实语义 | 目标数值结果失效 |
| reset | 不变 | 恢复该view的baseline轴/值/语义 | 目标分支结果失效；不切换到L0 |
| 新 grouping/代表选择 | 新run/新quantification | 创建新L1/L2及新baseline | 旧分支保留历史，不覆盖 |
| 仅L3候选/等级变化 | 新annotation version | 不变 | 纯数值结果保留；依赖标签/类别的解释图失效 |
| 样本分组/批次字段变化 | 根历史快照不变 | current/baseline按sample_id更新obs | 所有分支中依赖该字段的结果失效 |
| 原始提取/质量轴重新生成 | 新root | 创建新视图，不嫁接旧feature ID | 旧分支明确历史；不自动迁移关系 |
| 合并 | 新composite root/映射 | 新分支 | 不继承可执行模型/原embedding为活动结果 |
| 切换视图 | 不变 | 完整恢复目标分支 | 恢复目标已有有效报告/图，不重算 |

## 已确认的用户决定与实施边界（不重复询问）

- 授权方式：各主阶段完成后只做本地提交。整个任务完成后才统一更新5007供用户验收；期间不重启任何服务。验收通过后才推送和按既有维护流程发布生产。
- 本次L2仅fixed_representative。其他定量method只保留扩展契约，执行时明确unsupported；不实现多离子求和、权重整合或自动换离子。
- 注释本次实现精确质量/分子式候选与证据导入；不自动生成MS/MS鉴定、不实现全新分子式枚举。候选仍不等于结构鉴定。
- 仅本次新离子功能的后台执行通路获授权；既有统计/提取/保存任务架构不做无关重写。后台结果仍按根/视图/用户/工作区修订复核后原子安装。
- 代表使用规模是每样本约1000细胞、500特征；测试构建该规模及少量样本合并场景，检查内存和候选边数量，不为更大无依据规模另造分布式框架。
- 质量精度通常5ppm，偶尔10ppm；按主计划对应字段及配置预设明确记录，不把所有入口阈值静默统一改写。甲醇正离子实验，允许关系遵循用户已确认的H、Na、K、NH4、失水/加氢及主计划化学表定义；不在数据层自行扩大离子库、推断未确认实验极性或设置新实验阈值。
- 用户不提供验证数据，优先完整功能交付并由后续使用验证。现阶段验收证据是合成/工程/浏览器/性能检查及用户实际使用反馈；不声称标准品、复杂基质或真实实验的化学准确率已经通过。
- 新分析存在已生成合格L1时推荐L1，否则推荐L0；不自动生成L1来阻塞普通分析，也不追溯切换旧项目/分支/结果。

开发自行解决：文件拆分、内部UUID生成、JSON规范化、摘要实现、分页与纯展示布局、候选事务结构、codec适配、fixture命名。数据schema/identity统一使用主计划scMM/ion/contracts.py、scMM/ion/identity.py，应用层使用data_views.py/catalog等既定所有者，不复制平行契约。除非出现影响科学定义、超出以上授权或确有现有信息无法判断的新问题，不重复向用户索要上述答案。

## 主计划建议提交组织与验收边界

- 数据契约提交：D1 + D2纯领域/目录核心（与主计划离子关系schema并行开发，先统一外键）。
- 完整工作流提交：D3 + D4基本接入（与归组、注释UI阶段合并）；提交前覆盖每种视图创建、切换、处理、保存、重开、报告。
- 跨边界提交：D5 + D6 + D4对比/时间分析/完整图报告收尾；提交前覆盖合并、未保存分支、维护恢复与引用回收，不推迟到验收后。
- API预览只是展示可计算子集与排除依据，执行按钮直接应用已明确选择的策略，不增加确认复选框或二次确认弹窗。
- 每阶段只提交相应任务文件，保持dev可测试；阶段提交不是用户验收，不自动推送或发布生产。期间不更新或重启5007/5006；全部阶段与检查完成后核对开发连接/任务，统一更新5007供最终验收。用户验收通过后才推送并按已约定发布流程处理生产。
- 最终报告区分：小型合成测试、本机浏览器、真实标准品/样品、用户验收、远端CI。用户已明确不提供验证数据；最终明确“功能与保守失败机制通过，待用户使用验证；尚无独立真实实验化学性能验收”，不能用更多合成用例冒充科学验收。
