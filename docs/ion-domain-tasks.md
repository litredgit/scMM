# 离子归组与注释领域任务卡

[主实施计划](ion-compound-plan.md) · [任务导航](README.md)

本页是待实施功能的详细任务卡，主计划的已确认范围、参数和默认决策优先。默认 L1 使用 reviewed_v1；探索自动模式独立可选。不得将任务卡记为已实现或实验验证通过。

本文件是计划，不是已实现能力。按主计划分阶段实施、检查和本地提交；服务及发布只在主计划规定节点操作。用户已确认完整离子归组、固定代表离子 L2、通用质量/分子式候选及外部证据导入；不实现多离子定量、自动 MS/MS 匹配或从头分子式枚举。可分里程碑实施，不能以只做同位素作为最终范围。各阶段本地提交，最终验收后才 push/release；新功能可局部后台，不恢复旧 M2。

## 0. 已核对的现状及约束

- 公开门面为 scMM/file/data.py 的 CyESIData，现有可变矩阵门面在 file/_dataset_processing.py，AnnData 接口在 file/_dataset_interop.py。不新增并行的 Process/SCData 主容器；原引用中的类名需以真实代码为准。
- 旧 deisotope()（file/_dataset_processing.py:290）是固定单电荷间隔、全体细胞过原点回归、最大碳数上限和贪心唯一分配；默认删列，可求和。保留旧 API 兼容性，不能直接复用为新默认算法或静默改变它的默认值。
- 网页 lipid_annotation.py:110 先搜库，再根据候选公式计算天然同位素，不是数据库无关归组。保留完整候选、逐样本证据、输入身份和人工审阅等设计，拆出可复用数值函数。
- lipid_annotation.py:16 已限制比例证据来自有溯源的未归一化/未插补非负强度；lipid_isotopes.py 已使用 OpenMS 精细分布与采集分辨率近似，不用单个固定差代替所有天然同位素。
- 现 lipid_network.py:171 以同一数据库 ID 构建加合物边；不能继续让 database_id 充当 empirical compound ID。
- 现 lipid_network_views.py:41 的固定代表离子逻辑可参考；不能把“完整候选只有一个数据库 ID”提升为结构已鉴定。
- 现 isotope_feature_ids() 的任一样本命中/人工接受是显示导出筛选语义，不能直接继承为 L1 自动排除资格。
- 现 ADDUCTS 含 [M+H-H2O]+，尽管 parameters.md 文字说不支持源内碎片。迁移时明确这只是失水离子形式的质量候选；不能视为已确认的母子碎片边。

## 1. 执行代理必须遵守的固定规则

1. Feature、关系、empirical compound、候选身份分开建模；不能把它们压成 var 中单个 name/group 列。
2. 原始 Feature ID 与强度不被归组或注释写回覆盖；L1 是列选择/映射，L2 是显式定量策略输出；不同轴不放同一 AnnData.layers。
3. 所有判定保存支持、反证、不可评估、冲突、输入身份、参数及算法版本。未校准的规则等级不能命名为概率/FDR。
4. 用户说明通常质量误差≤5 ppm、偶尔≤10 ppm，甲醇溶剂，正离子常见 H/Na/K/NH4 及去水加氢；每样本≤1000细胞/500特征。作为可配置候选规则与资源设计背景，不能把这些描述升级为归组准确性证明。实际采集 resolution 尚未知且必须由采集配置填写，不能仅据仪器型号猜；其他未定义检查用显式参数与 not_evaluable/pending 记录，不能照搬 LC-MS 阈值。
5. 当前优先完整功能与合成反例验证；用户暂不提供验证数据，真实有效性由用户后续使用验收。实现参数化引擎及保守规则状态，缺必要采集信息时该检查明确 not_evaluable，不能据此全自动排除峰；不把缺真实资料作为不交付候选/审阅/L1/L2功能的理由。软件规则与预设明确为待实验验证，不称已校准高置信度。
6. 化学候选是必要约束，相关仅辅助；共同细胞脉冲、全细胞相关、总强度、数据库同名均不能独立建立归属。
7. 人工接受/人工定量指定作为独立声明保存；既不改写算法原始检查值，也不自动把冲突边升级为已验证事实。
8. 所有稳定 ID 以数据集命名空间和不可变内容身份生成；不同运行相同 m/z 不自动等于同一 Feature。重跑的版本 ID 与实体 ID 区分；跨版本继承需显式映射。
9. 所有领域函数无网络/服务/磁盘副作用、不改输入矩阵；外部文件解析、路径检查、授权及原子发布在应用层。
10. 支持自然丰度和示踪输入区分；示踪标记不能当作异常天然同位素自动去掉。本计划实现示踪证据导入/链接，不承诺未定义的示踪定量算法。

## 2. 建议模块与公共纯函数契约

新增 scMM/ion/ 作为领域包，统一模块：contracts.py（类型与 schema）、species.py（离子/同位素/质量目录）、relations.py（索引及所有候选关系）、hypotheses.py（受约束假设）、representation.py（L1/L2固定代表量化）、annotation.py（通用候选及旧脂质适配）、evidence.py（导入证据、作用域、人工断言及报告标准；内部数值证据由relations.py计算）、identity.py（内容身份及稳定 ID）。应用层数据库 catalog、数据分支与存储独立，不把数值或磁盘读取堆入 HTTP 路由。

建议 dataclass(frozen=True) + 类型化表结构；复杂枚举显式 Literal/Enum，JSON 不允许 NaN/Infinity。对大型矩阵只读分块取列，不在每条候选上整体 densify/copy。

```text
validate_grouping_input(data: FeatureInput) -> ValidatedFeatureInput
validate_ion_specs(specs: Sequence[IonSpec]) -> IonCatalog
build_mass_index(features: FeatureTable) -> MassIndex
find_isotope_candidates(data: ValidatedFeatureInput, catalog: IsotopeCatalog,
                        policy: IsotopeSearchPolicy) -> RelationBatch
find_ion_form_candidates(data: ValidatedFeatureInput, specs: IonCatalog,
                         policy: MassSearchPolicy) -> RelationBatch
find_fragment_candidates(data: ValidatedFeatureInput, losses: LossCatalog,
                          policy: FragmentSearchPolicy) -> RelationBatch
measure_relation_evidence(data: ValidatedFeatureInput, relations: RelationBatch,
                          policy: EvidencePolicy) -> EvidenceBatch
infer_group_hypotheses(data: ValidatedFeatureInput, relations: RelationBatch,
                      evidence: EvidenceBatch, policy: GroupingPolicy) -> GroupingResult
assess_l1_eligibility(grouping: GroupingResult, evidence: EvidenceBatch,
                      policy: L1Policy) -> L1DecisionTable
build_l1_mapping(features: FeatureTable, decisions: L1DecisionTable) -> RepresentationSpec
choose_quantifiers(data: ValidatedFeatureInput, grouping: GroupingResult,
                   evidence: EvidenceBatch, policy: QuantifierPolicy) -> QuantifierTable
quantify_groups(data: ValidatedFeatureInput, grouping: GroupingResult,
                quantifiers: QuantifierTable, strategy: QuantificationStrategy) -> QuantificationResult
search_compound_candidates(targets: AnnotationTargets, db: CompoundIndex,
                           policy: AnnotationPolicy) -> CandidateBatch
validate_evidence_import(payload: EvidencePayload, source: EvidenceSource) -> EvidenceBatch
link_external_evidence(targets: EvidenceTargets, imported: EvidenceBatch,
                       mapping: ExplicitEvidenceMapping) -> EvidenceLinks
assess_identification(candidates: CandidateBatch, links: EvidenceLinks,
                      standard: ReportingStandard) -> IdentificationAssessment
migrate_lipid_annotation(old_version: Mapping, data: ValidatedFeatureInput,
                         migration: MigrationPolicy) -> MigrationResult
```

不为这些函数开放任意函数名 HTTP 执行。Python 新入口使用 scMM.ion 显式函数和 AnnData；网页通过应用层明确方法调用，CyESIData 旧门面继续兼容，不另起数据容器。

### 2.1 输入字段（D0 负责实现）

FeatureInput：dataset_id、feature_axis_id、cell_axis_id、intensity_source_id、content_digest、extraction_version、calibration_version、features、cells、intensity_accessor、optional_feature_snr、optional_detection_mask、optional_blank_summary。

FeatureTable 每行：feature_id、mz、mz_uncertainty（可空，不能凭 ppm 参数伪造观测不确定度）、polarity（pos/neg/unknown）、acquisition_run_id、resolution_model_id、extraction_method、integration_definition、quality_status、quality_evidence_ids。m/z 为正有限 float64；feature_id 唯一，允许同 m/z 不同 ID。

CellTable：cell_id、sample_id、acquisition_run_id、可选 condition_id/biological_replicate_id；缺失 biological_replicate_id 不从 sample 名猜测。所有矩阵与表顺序及轴身份核对。

IntensitySource：单位、raw/linear_background_corrected/normalized/transformed/unknown 来源、背景处理方法与版本、插补状态、负值语义。未定义负背景校正值不能直接截断为零后用于比例；原始强度中的零是否表示未检出由提取契约说明，不根据数值自行断言缺失。

### 2.2 输出表公共字段

Relation：relation_id、left_feature_id、right_feature_id、relation_type、direction、hypothesis_roles、ion_spec_ids、isotope_order/components、neutral_loss_formula、expected_mz/expected_delta、observed_delta、signed_mass_residual、residual_unit、mass_tolerance_policy_id、source_evidence_ids、status、reason_codes。一个 Feature 对可有多条不同解释；禁止按节点对去重丢掉关系类型。

Evidence：evidence_id、relation_or_group_or_candidate_id、sample/run/condition_scope、check_name、check_version、observed_value、expected_value/interval、units、n_valid、n_parent_only/n_child_only/n_both/n_neither、status(pass/fail/not_evaluable/pending)、reason、source_id。记录实际 mask/阈值来源；比例及相关为不同证据行。

GroupingResult：grouping_version、input_identities、policy_id、ion_catalog_digest、relations、evidence、hypotheses、memberships、conflicts、singletons、unresolved_components、search_diagnostics。

Hypothesis：hypothesis_id、component_id、empirical_compound_id、neutral_monoisotopic_mass_interval（可空）、canonical_mass_estimate（有定义才填）、mass_estimator_version、charge/adduct/oligomer/isotope roles、support_evidence_ids、conflict_evidence_ids、status(candidate/accepted/ambiguous/rejected/unresolved)、acceptance_policy_id、manual_assessment_id、search_complete。

Membership：hypothesis_id、feature_id、ion_spec_id、charge、isotope_role、oligomer_n、membership_role(core/possible/fragment_link/overlap)、exclusive、evidence_ids。多假设/重叠是正常结果，不能靠取排序第一消除。

## 3. D0：输入、离子规则和质量定义

依赖：无；完成后解锁 D1-D4，可并行。

- IonSpec 字段：id、label、polarity、signed_charge、neutral_molecule_count、added_elements、removed_elements、radical/electron convention、category(adduct/charge/oligomer/fragment_form)、source、version、enabled_for_search、enabled_for_quantification。
- 通用离子式：mz = (n*M + mass(added) - mass(removed) - z*m_e) / abs(z)。M 是中性单同位素质量，n 是分子数，z 是有符号电荷；以所选元素质量版本计算，不混用旧近似常量和新元素质量。
- 正负 z=1、z=2 均可表达：例如 [M+H]+、[M+Na]+、[M+K]+、[M+NH4]+、[M-H]-、[M+Cl]-、[M+HCOO]-、[M+OAc]-、[M+2H]2+、[M-2H]2-；其他混合双电荷规则和多聚体通过声明式目录加入。目录支持能力不代表它们在当前实验必然存在。
- n=2 及显式 n>2 多聚体语法可校验和搜索；默认候选目录到 n=2；其他合法 n 由显式规则配置，见主计划软件草案，不推断实际检出。不允许解析用户任意 Python 化学表达式。
- 表面标签不能决定质量；原子组成、signed charge、n 才是计算依据。候选公式给出后，移除元素数超出组成则该角色不成立，保留失败理由。
- polarity=unknown 可以输出“待采集极性确认”的候选，但不跨正负假设自动接受。跨运行/跨极性关联必须有显式样本、实验和对齐映射；单细胞不同批次不能构造不存在的一对一细胞。
- 质量残差与容差的参考定义分开：观测离子 ppm、关系 delta 的 Da、共享中性质量区间不可混称同一 ppm。使用 float64、排序二分/区间索引，边界仅加机器舍入保护。
- 理论常数来自锁定的元素表/同位素表；记录依赖版本及表摘要，不能给出看似实验阈值的常数。

验收反例：正负电子质量方向错误、z=2 除法遗漏、[2M+H]+ 忽略 n、同 m/z 两 ID 合并、错误极性、未知组成负原子计数、NaN/Inf/负 m/z、零电荷、重复规则、未明确极性自行取 pos。

## 4. D1：数据库无关天然同位素候选与证据

依赖：D0。

- 候选生成支持 abs(z)=1/2；先用锁定同位素质量差（包括 13C 等配置元素）寻找精确间隔和可能阶次，再构建兼容同位素包络假设。z=2 预期同位素间距相应除二；不因约 0.5017 或 1.0034 单个间隔直接定电荷/删峰。
- unknown formula 分支保持 formula-free：碳数估计、可行元素/碳数区间和化学约束是包络假设，不能假装已有具体分子式。只靠最大碳丰度上限通过不能获得高资格。
- 不是所有 M+2 都是两个 13C；目录区分不同同位素细组分。分辨率模型决定可分辨/可合峰的理论表现；不可分混合只记录“无法排除”，不做不存在的 deconvolution。
- known formula 分支复用当前 OpenMS fine_distribution/resolved_distribution 思想，扩展 charge 和 n；计算加合物/多聚体实际离子元素组成与相应同位素概率。母峰可能是非 M0、M0 未检出时保留多个起点/中性质量解释。
- 每样本保留质量、总强度比、共同检测比例、有效细胞、母缺子有、比例随强度/批次变化等证据；总强度比与单细胞比例分布均输出，避免少数高强度细胞支配时不可见。首版固定报告总量比和有效单细胞比值的中位数/四分位数，不生成模型置信区间；证据阈值和探索初始值使用主计划。
- 缺失次级同位素不是自动反证；若理论本应可检出且检测限证据充分才可形成缺失证据。低信号不可评估不同于失败。
- 共检出相关可作为辅助，不以相关阈值强制未知低信号同位素关系失败；相关仅提供辅助状态，不独立决定接受，L1资格遵循主计划reviewed_v1/exploratory_v1。每样本计算，不能跨不同生物条件混算使组间均值驱动相关。
- 冲突：同一峰可同时是另一个分子的单同位素峰及本组同位素混合；多母峰解释、同位素同量异位、理论比例不一致均保留。支持包络不等于信号纯度已证实。

测试：z=1/z=2 的已知谱、M0 缺失、M1 缺失但有 M2、C13 与 N15/硫/钾细结构、分辨率不可分峰、真实独立代谢物偶然质量差、被细胞总量驱动的高相关、同一峰两母来源、比例仅一个样本通过、低细胞不可评估、零子峰参与、常数向量、稳定同位素示踪被标记为非天然适用。

## 5. D2：单/双电荷加合物、多聚体和源内碎片候选

依赖：D0；可以与 D1 并行。

### 5.1 加合物与电荷关系

- 对每个 Feature 展开被启用的 IonSpec 中性质量区间；用区间索引连接有相容 M 的其他 Feature/离子角色。目标是共享中性质量假设，不能只对几种固定 delta 做无角色匹配。
- 跨电荷关联既检查 m/z→M 一致性，也连接 D1 的电荷包络证据；多个电荷可能时均保留。
- 两个峰都匹配某数据库候选只能作为注释条件证据，不能替代无数据库离子关系。没有可见同位素仍允许候选加合物关系，但不自动升级。
- 不要求不同加合物跨细胞比值固定；相关和共检出只辅助。检出条件/盐变化造成的比值改变不得单独证明不同化合物。

### 5.2 多聚体

- 同时验证 n*M 与各角色的电荷/同位素假设；保留 n 及“分子聚集离子”类型，不把 [2M+H]+ 的 m/z 当 M 单体。
- 多聚体与单体共享中性单体质量可构成同一化学家族的候选，但聚集响应依赖浓度/离子环境，不与单体求和；是否计入 empirical compound 核心成员由证据策略明确。
- 混合异二聚体没有给定组成不能从两峰差直接求唯一结构；输出未支持模型/未知候选，不做盲目组合爆炸。

### 5.3 源内碎片与中性丢失

- LossSpec：元素组成、质量、方向、适用电荷/离子类别、参考来源、是否有实验验证。H2O 等只作为候选模板。
- 按电荷/离子角色计算母子关系；同样质量差可来自两个独立代谢物，保存 alternative_independent_feature 冲突。
- 碎片边默认 relation-only；不提供将两个 empirical compound 合并的传递闭包，不自动触发 L1 去掉子峰，不作为 L2 定量来源。
- 同方法标准品源能量阶梯、隔离明确的 MS/MS 或其他直接支持可把证据增强为 experiment_supported；群体 MS/MS 的归属与源内碎片证据分开。即使有结构片段匹配，也不能自动证明所有单细胞 MS1 子峰都纯来自该母峰。
- 允许多父碎片候选与独立候选并存，不取最高相关母峰强制归属。

测试：正负模式相同质量峰不串组、H/Na/K 互换、z1↔z2、离子形式误判造成的中性质量假交集、二聚体与恰好同质量独立代谢物、损失方向/电荷错误、18.010565 Da 独立两化合物、碎片桥接两个本来不兼容组、强相关但无化学约束、支持来自群体却被误传播至所有细胞。

## 6. D3：受约束图、竞争假设与 empirical compounds

依赖：D1+D2+evidence。

### 可直接实现的局部枚举算法

- species hypothesis 将 Feature i 的观测区间 [a_i,b_i] 映射为中性区间 J_i(s,k)=[(|z_s|*a_i-shift_s-isotope_delta_k)/n_s,(|z_s|*b_i-shift_s-isotope_delta_k)/n_s]。shift_s 含元素增减与电子质量；同位素 delta 以实际离子/多聚体组成定义，不能再除/乘错 n 或 z。没有观测不确定度时，[a_i,b_i] 是已确认质量容差模型下的可行匹配区间，字段标 matching_interval，不能冒充估计的测量置信区间。
- isotope-only、adduct 未知时保留 envelope mass 与 neutral alternatives；没有有限候选 adduct/z/n 时 neutral mass 字段为 unknown，不能把最低 m/z 强写为 [M+H]+ 再反算唯一 M。
- role slot=(采集/对齐范围、ion_spec_id、z、n、同位素理论可分辨组分/合峰槽)。同一假设的一个 slot 最多一个 Feature；同 nominal M+2 的可分辨细峰是不同槽；分辨率下合并的细组分只占一个槽。两个稳定 Feature ID 竞争同一槽时保留备选，不能按相近 m/z 合并 ID。
- 从每个可行 species hypothesis 锚点做确定顺序 DFS/分支限界。状态保存 (I_common, assignments, occupied_slots, used_features, evidence/conflicts)。加入候选角色时先做 I_new=intersection(I_common,J_i)，再检查 slot、Feature 角色互斥、可行包络及全组残差；空交集或硬冲突则拒绝这条搜索分支。加入或排除候选均保留可能解释，不能用取最大组代替竞争。
- 输出非冗余的兼容核心假设及其互斥/包含关系；同样成员但不同离子身份/同位素起点仍是不同解释。不能仅保留最大节点数方案。候选支持只用于确定搜索顺序或显式剪枝上界，不把概率未定义的分数差当接受标准。
- 所有完整竞争解集合计算完之后，才标注跨解不变的 core membership 与可变 possible membership。两个化学实体可能共享未分辨 Feature 时标 overlap，保留独立实体候选及混合解释；该峰不分配到两个可直接定量的 L2 变量。
- 中性质量区间有交集只是必要条件；必须有已确认化学证据策略支持实体判定。adduct-only 同质量相容、共同脉冲/相关均不能独自消除独立化合物解释。
- 工程预算达到即封存该组件已枚举结果及未探索状态摘要，search_complete=False/unresolved，保留完整输入候选；不截断候选后再说“唯一”。接受或 L1 排除不得依赖不完整搜索。

### 完整竞争解与人工选择的精确定义

1. 完整解是在局部启用角色的分支均已处理后，为每个Feature给出核心归属、共享/混合状态或未归组；不要求并完所有节点。
2. 一个分组/拆分解释下的角色配置包括成员、ion/isotope角色及共同质量区间；未知adduct保留条件质量多解。
3. 在同一解释内，仍可加入相容角色的真子配置只是搜索中间状态；输出局部极大相容配置去重，不按最大节点/最少组择优。
4. 不同分组、拆分、独立物质、重叠和离子角色解释分别保留；不能因成员是另一解释的子集就删除独立解释。
5. core/possible仅对同一分组解释下的完整角色配置集合计算，不对全组件任意子集求交集。
6. 成员相同但adduct/电荷/中性质量不同是identity alternatives；成员不同或实际共享是competing grouping alternatives。
7. reviewed_v1可人工选定一个硬约束合法的分组解释，接受依赖关系及表示决策；服务器复核来源、范围、搜索完整性和量化资格。
8. 未选化学可行软解释保留alternatives，不改写为数值失败，也不因此永远阻止已审阅解释生成L1。
9. 独立物质的逻辑可能性可留作软备选；不能把MS1无法排除所有巧合当作永久硬阻塞。实际混合/共享证据仍阻止相应量化。
10. 人工不能跳过空质量交集、同槽矛盾、过期来源、不完整搜索、未解决混合/共享及一个Feature重复计量。
11. exploratory_v1使用主计划2.3的证据层级；同资格且成员不同的解释保持ambiguous，不以ID、遍历顺序、成员数或强度决定化学归属。
12. 只有identity alternatives、成员和表示一致时可接受成员关系但保留质量多解；预算耗尽的暂时唯一不构成接受资格。

### 固定算法行为

1. 节点为稳定 Feature，关系为多重有向/无向候选边；先按明确的采集/对齐范围分区。连通分量只用于减少搜索量，不能直接输出为一个化合物。
2. 以离子角色及同位素包络生成锚点，枚举/约束传播一组共同中性质量区间、角色分配和同位素起点。没有电荷/加合物唯一解释时保留多种 M；“只有同位素包络、未知加合物”允许 mass unknown。
3. 硬约束：所有核心成员存在相容的共同 M 区间；离子角色、电荷、n、同位素位移互容；任一闭环不出现超容差累积漂移；Feature 的竞争归属/重叠显式保留；不存在用碎片边替代核心共同质量约束的路径。
4. 同一对峰的多种解释各自是一种 hypothesis；多个同位素证据来自同一次观测/同一父候选时去重计来源，不当作多条独立证据。数据库候选与由该候选计算出的同位素证据之间的条件依赖保留。
5. 不采用“边越多分越高”自动选大组。候选排序可使用明确的字典序证据规则用于审阅，但 accepted 需要通过已确认的 acceptance policy，并且与竞争解释的差异证据明确；并列不能按 feature_id 决定科学归属。
6. 输出核心成员、可能成员、混合/重叠成员、碎片外链、互斥假设、单例及拒绝原因；Feature 可参与多个未解决假设。不能为了“一行一个 group_id”抹掉多归属。
7. 图规模大于确定资源策略时采用受控分支限界/搜索容量。资源上限是工程参数，须显式记录；没有完成的组件标 unresolved、search_complete=False，不把前 K 个方案当作完整结果，也不据截断结果自动接受/L1 删除。
8. 计算确定性：输入顺序变化、线程顺序变化不改变候选集合、ID 或证据；排序仅用于稳定输出。随机近似若后来引入必须记录 seed 和完整性限制。
9. 手工合组/拆组是新版本的操作声明；先检查硬约束。用户要求保留冲突解释时保留为 manual_override/conflicted，而非伪造算法通过，也不自动获得 L1/L2 资格。
10. empirical_compound_id 仅标当前数据集内的实验实体；跨项目/数据库/名称相同不共享实体。单例保留为 ungrouped feature/entity，不能在展示中把单例数也称为已确认化合物数。

验收反例：A-B 与 B-C 边各通过但 A-C 不相容的串接；两个近等质量候选通过桥峰连成超组；一个峰两种单体身份；同名或同分子式异构体不同实体；多个库记录为同一观测虚增支持；单个碎片桥；缺同位素；所有节点孤立；质量区间交集为空；搜索截断；输入行列打乱后结果不变。

## 7. D4：L1 资格与非冗余 Feature 视图

依赖：D3。须完整交付该视图，不能将仅显示筛选当作完成。

- L1Decision 行：feature_id、action(retain/omit_from_view)、representative_feature_id、relation_ids、hypothesis_ids、scope、eligibility_checks、reason_codes、policy_version、manual_override、source_feature_axis_id。
- 两种表示和两种决策模式全部实现，资格逐项遵循主计划2.3表。默认reviewed_v1要求人工接受及硬约束，未知公式的理论比例not_evaluable不额外阻塞；exploratory_v1按草案规则计算，不宣称实验校准。
- 自动排除必须同时满足：存在有效未变换证据来源；包络/质量检查达到已确认策略；归属在该视图所覆盖的样本/运行范围内无未解竞争；非混合/重叠信号；保留代表离子；search_complete=True。未知信号保持 retain。
- 不能沿用“任一样本 matched 就从全项目删掉该列”。允许子集范围单独建视图，但 L1 schema 记录范围；整个研究统一视图不能让各组有不同的变量定义。
- M0 原始值保持原样，不把同位素加上去；M0 检出差时不能逐细胞改用最亮 isotope。若项目固定选另一个稳定代表峰，须是独立 representation policy，明确其解释和适用组，原始值不被校正改写。
- 一个 Feature 同时是另一实体候选或有无法排除的混合时保留；没有充分判定力时宁可无去冗余，而不是制造“准确率高”的删峰数。
- L1 通过映射/索引构建，改变变量轴后新建 AnnData 表示。相同轴的 raw/normalized/log/scaled 才放 layers；全量 L0 独立保存。
- 已生成且有效的合格L1可推荐给新分析；未生成则L0。默认仅人工接受且通过硬约束的关系；没有真实数据不阻塞实现或该模式使用。既有项目、分支及结果不自动切换。

测试：只有一个样本通过其余冲突、独立代谢物重叠、子峰归多个母峰、M0 缺失、代表本身被另一规则排掉、所有未知保留、重复运行不永久丢峰、子集和全项目范围区分、切换 L0/L1 后能回溯原始 Feature。

## 8. D5：L2 固定代表离子及扩展策略契约

依赖：D3，独立于数据库身份；可与 D4 并行。

### 8.1 固定代表离子策略（完整实现）

Quantifier 行：empirical_compound_id、hypothesis_id、quantifier_feature_id、ion_spec/charge/isotope/oligomer role、selection_method、eligibility_status、excluded_features/reasons、per_sample_metrics、manual_selection_id、training_scope、quantification_policy_id。

- 先检查候选量化资格：非混合/重叠、身份来源有效、availability=true位置的有限非负线性响应、足够检出、若有饱和/背景/响应漂移证据则明确排除或降级。没有饱和数据不能标“已排除饱和”。
- 选择顺序使用主计划：合法性/排除检查后，各样本等权检出率→各样本等权原始平均强度→稳定feature ID破完全并列；不根据组间差异或分类表现选择，不留待另行定稿。
- 全项目固定一列；不按细胞、条件、显示范围替换。不因某条件更亮就切换加合物；缺值保持原有零/未检出语义，并记录 coverage，不自动用另一离子原值填补。
- “选择代表”不等于绝对定量。输出为指定离子的相对响应；可不知道物质名字，也可不知道加合物唯一解释，但成员关系和该代表的可解释性需通过量化 policy。
- 归组可靠但没有合格代表时，保留 group，quantification_status=not_available，不能生成全零组或把该 group 从证据表消失。
- singleton 是否进入 L2 由明确 include_singletons 策略决定；进入时标 ungrouped，不能当作证明独立化合物。未解决共享峰不能重复用于两个已提交 L2 定量变量。
- 输出 QuantificationResult(matrix, variable_table, feature_to_variable_mapping, cell_axis_id, source_identities, policy, coverage, availability, missingness_reasons, unavailable_groups, diagnostics)，保持来源和变量单位。

### 8.2 其他量化策略仅预留契约，本任务不实现

- 本任务 QuantificationStrategy 只接受 strategy="fixed_representative"。预留 strategy schema/version 字段及未来 CalibrationSet 引用位置，不实现拟合、响应系数估计、同位素求和、跨离子填补、加合物求和或多离子共识。
- 任意其他 strategy（包括 calibrated_linear、ratio_scaled_consensus、isotope_sum）必须返回明确 unsupported_strategy/not_implemented；不得静默切换到代表，也不得生成看似可用的组合矩阵。
- 本次L2代表来自合格完整单体观测离子；多聚体/源内碎片不作为本次化合物定量代表。人工接受其关系只增加附属/外链证据，不绕过该资格。无合格代表时保留实体并报告不可量化。
- 不存储未经实施的 CalibrationSet 拟合模型；未来扩展仅通过独立版本化策略。L2 代表/量化策略改变形成新 representation version；L3 名称更新不自动改 L2。

测试：离子响应比例因盐/批次改变、两个细胞数量差异大的样本、选择规则用条件标签导致泄漏、逐细胞最亮切换、无代表的可靠组、一个峰被两组重复量化、任意求和错误、多聚体平方浓度响应、不支持策略明确报错且不产生矩阵、缺离子时不跨离子填补、单次项目重载代表不变、注释名称改动矩阵不变。

## 9. D6：通用化合物候选与现脂质能力迁移

依赖：D0；有 Feature targets 即可并行开发，group targets 等 D3。

### 通用候选引擎

- 输入目标可为 Feature-ion hypothesis、empirical compound neutral-mass hypothesis、formula hypothesis；明确 target_type/target_id/hypothesis_id。Feature 原有候选继续可用，不能为了按组注释丢掉与组不相容的独立物质候选。
- CompoundIndex 以来源和版本化记录为实体：database_namespace、source_record_id、record_hash、neutral_formula、exact_mass、formula_mass_consistency、names、synonyms、structure identifiers、ontology/class、lipid structural level、origin metadata。
- 中性质量/公式索引支持非脂质代谢物数据库及用户表格/SDF；核心不硬编码 LMSD 字段。本任务只检索给定数据库/外部来源已有的中性质量和分子式候选，不做从头公式枚举。用户未提供分子式时允许保持 unknown。
- 先做确定的质量/极性/离子形式相容搜索，保留所有容差内候选。检索容量超限要显式分页/未完成，不能默认只保留 top-N 冒充全候选。
- 公式证据和结构记录分层：一个公式可有多个结构；不同库同结构可建 cross-reference 但保留来源记录；同名不合并，同分子式不去重成一个结构。同结构的立体异构边界依所用 ID 明确。
- Candidate 行：candidate_id、target_type/target_id/hypothesis_id、database_namespace/record_id/hash、formula_id、structure_id/identity_resolution、neutral_mass、ion_spec_id、theoretical_mz、signed_ppm、mass_status、isotope_evidence_ids、msms/standard evidence links、classification_assertions、rank_components、rank_policy/version、manual_selection、conflicts。
- 排序与证据资格独立；规则排序可保留现类别/加合物规则，但只解释成启发式排名。不能从候选第一名推断检出、结构唯一、鉴定概率、通路存在。
- 注释有4个分离维度：feature_quality、ion_group_confidence（规则状态）、identification_assertions、biological_origin_evidence；不合并为单一 calibrated score。
- 脂质标签按证据最低共同结构层级报告；数据库名称含链位/双键位点不能因准确质量匹配就直接展示为实验支持的解析层级。

### 兼容与迁移

- 保留旧 lipid_annotation JSON schema 1 的只读读取和原始快照；用 annotation.py 中的显式脂质适配函数把完整候选、逐样本关系、数据库身份、人工选择及网络辅助映射到通用 schema。
- 旧 candidate_id/relation_id 可保留为 source_legacy_id，并建立明确新旧映射；不根据显示名重生成关联。
- 旧人工选择迁为 manual candidate assertion，不自动生成 identified/confirmed；旧网络支持等级作为 legacy_heuristic_evidence，不直接转新归组 accepted。
- 旧 [M+H-H2O]+ 候选迁为 fragment_form hypothesis，不自动创建已确认的源内碎片关系。
- 保留现 lipid rules、分类饼图、feature network、代表离子图的来源解释，迁移后显示候选/多义/未注释的分母规则一致；数据库实体网络与 empirical compound graph 名称及 ID 分开。
- 旧 API CyESIData.get_annotation/deisotope 不变；新通用能力经显式方法调用。不要求老项目在打开时联网、重新搜库或自动重跑。

测试：同公式异构体、同名不同结构、跨库重复与立体异构、库公式/精确质量不一致、非脂质用户库、无候选未知组、同一 Feature 多离子假设、多组共享候选、分页完整性、人工选首名不升级鉴定、迁移前后原候选/人工记录/强度逐项不变、旧网络级别不冒充归组证据。

## 10. D7：经验、标准品、群体 MS/MS、空白/示踪证据导入

依赖：D0；可与 D1-D3 并行，集成依赖 D6。

### 通用导入 schema 与边界

- 支持JSON和CSV/TSV证据清单、受限MGF/MSP峰表解析及已有外部匹配结果导入；不执行自动谱库匹配或任意供应商二进制库解析。原始mzML报告可作为受控引用/附件，不额外承诺全新原始MS/MS处理流水线。
- 领域函数校验标准化记录；应用层负责读取文件、内容 SHA、路径范围、大小/资源限制、原子存储。禁止 pickle/任意可执行对象导入；不将频谱二进制塞进 H5AD.uns。
- EvidenceSource：source_id、type、file_hash、schema/version、citation、creator/date、instrument/method、polarity、sample/run IDs、biological/context scope、processing software/version、manual/import origin。
- EvidenceRecord：evidence_id、assertion_type、target_ref、observed/expected、units、tolerances、spectrum_ref/hash、candidate/formula/structure refs、scope、positive/negative/inconclusive、review_status、limitations。
- target_ref 必须明确 Feature/组/候选/外部物质 ID 及版本；只有 m/z 的记录先进入 unmatched/ambiguous，不能强行取最近峰。外部 source record 与当前 Feature ID 不同名字需显式映射表。
- 导入先生成审阅结果 matched/ambiguous/unmatched/rejected 与理由；整批结构校验失败不污染当前证据，允许明确逐记录隔离的导入模式但必须报告数量。

### 经验/文献/专家规则

- 支持 instrument/method-specific adduct observation、neutral loss hypothesis、class rule 等声明式记录。经验规则可约束/排序，缺直接数据时不能当标准品确认或独立 MS/MS 证据。
- 记录“在哪些条件观察到/未观察到”，不把其他方法已知离子形式当当前样品检出证据。

### 标准品/混合物

- 记录标准物质标识/纯度、已知配比/浓度、仪器源参数、基质、空白、单品/混合品/加标方式、运行映射与原始报告。
- 可导入同位素包络、加合物/电荷/多聚体响应、源能量阶梯、质量偏移、响应校准及干扰证据。用同方法结果评价归组真阳性/错误合并/拆分；跨方法证据保留适用限制。
- 标准品存在不等于每个单细胞都有该化合物；匹配的结构断言适用于明确观测/实体与方法范围，不能把候选所有同质量峰全确认。

### 群体 MS/MS/谱库

- schema必须有precursor_mz、charge/polarity、ion/adduct hypothesis、isolation_window、collision_energy/method、instrument、sample pool/run scope和spectrum provenance字段；实际缺项用unknown/null并报告不足，不造值。缺映射身份时进待匹配区；缺隔离/碰撞信息不能支持需要这些信息的更强断言，但不阻止保存有限证据。
- 保存 library identity/version、matching algorithm/score definition、mass/fragment tolerance、matched peaks/count、coverage、decoy/error-rate validation（有才填）、chimeric/contamination status。
- 如果标准化导入记录附带峰列表，则校验 m/z/强度有限且强度非负；不计算新的自动 MS/MS 匹配分数，已有外部匹配分数不统一换成概率。库匹配不清楚结构分辨能力时只给能支持的结构层级。
- 群体数据支持某批样品的身份候选，不证明某个单细胞峰的唯一来源，也不能把不能分辨的异构体归为唯一结构。宽隔离/共隔离要保留竞争候选和 scope。

### 空白、加标、稳定同位素

- 空白/背景及加标恢复用于 biological_origin_evidence/quality，不能只凭数据库命中证明生物来源；空白存在也不默认删除全部生物信号。
- 稳定同位素记录标记类型、元素丰度/标记设计、时间/条件与对照范围；天然同位素模型标 not_applicable 或使用显式校正模型。导入示踪支持与真正的 isotopologue 定量是不同功能；未定义后者保持 pending。

### 鉴定报告标准

- ReportingStandard 显式选择名称及版本；内部保存具体 assertions/criteria，再按 MSI/Schymanski/LSI 所选标准进行映射，禁止机械地跨标准转换等级。
- 标准品同方法对照、MS/MS、质量、同位素支持分别保留；只有符合标准全部适用条件时输出相应级别，否则返回 unresolved criteria。
- 输出最大支持结构层级（formula/class/sum-composition/chains/positions/stereochemistry 等）与未解决候选集。人工指定不是自动满足某个等级。

测试：错版本 Feature ID、同 m/z 多匹配、外部标准来自不同极性/源设置、宽窗口群体混合谱、谱库分数被误当概率、证据作用域错误扩散、不同谱库结构相互冲突、空白与生物两来源并存、天然模型用于重标记失败、未知级别、不完整标准品元数据、导入中失败/重试去重、内容 hash 改变使链接待复核。

## 11. D8：化学正确性、统计敏感性及规模评价

依赖：D1-D7；合成可先随任务执行，真实评价等实验资料。

- 评价单位明确区分：边关系、包络、组/成员、代表量化、身份断言。分别报告 precision/recall（有真值）、错误合并、错误拆分、neutral mass residual、歧义保留与错误自动决定数量。
- 量化指标按有校准数据的条件报告：线性/重复性、离子选择稳定性、跨基质/盐/批次偏差、缺失覆盖；没有真实浓度不能报告定量准确率。
- 固定合成真值覆盖 z1/z2、正负、多聚体、碎片、异构体、未分辨重叠、低信号、缺峰、共同细胞总量、样本不均衡、所有未知和搜索截断；不以删峰越多越好。
- 真实数据评价理想资料包括标准品、已知混合物、基质、空白、技术重复/独立生物重复与 MS/MS；用户当前明确不提供资料，由后续使用验有效性。本任务交付合成检查与完整导入/审阅功能，真实准确性标待验证，不能以运行无报错替代。
- L0/L1/L2 比较固定同一细胞集合、合理可比的预处理与随机 seed；报告 PCA 解释率/载荷贡献、邻域/聚类稳定性、差异结果冗余和方向、监督按生物重复划分的性能。比较不变不证明化学归组正确；比较改变也不自动证明更好。
- Fold Change 使用定义的非负量化层，不能从逐特征 z-score 直接求。L0/L1/L2 各自保留 normalization denominator/feature-universe，避免删峰后总量归一化分母改变却归因于算法本身。
- 代表选择、特征过滤、插补、批次校正等处理的监督验证必须说明训练范围与泄漏边界；没有完整折内预处理不可宣称已消除泄漏。
- 规模检查记录 features/cells/samples、候选关系密度、搜索组件大小、时间、进程峰值内存、完整/未解决数量；工程容量独立于实验阈值。不得用候选截断把大输入“成功”变成不完整但未披露输出。

## 12. 测试文件、blocks 与验收映射

新增领域测试建议：
- tests/domain/test_ion_specs.py（D0）；test_ion_candidates.py（D1/D2）；test_ion_evidence.py（证据）；test_ion_group_hypotheses.py（D3）；test_ion_representations.py（D4）；test_compound_quantification.py（D5）；test_compound_candidates.py（D6）；test_compound_evidence_import.py（D7）。
- 共享小型合成构造 tests/support/ions.py，不提交大谱/矩阵；与旧 tests/support/lipids.py 的字段转换单测集中适配层，不导入别的测试文件。
- 保留并调整 tests/domain/test_annotation.py、test_lipid_annotation.py 的旧兼容及迁移测试；test_data.py、test_h5ad_interop.py 验证门面/轴/保存不丢原始信息。应用、API、浏览器应由主计划另列。

建议在 tests/blocks.json 新增 ion-grouping（而非所有新包都混进 annotation）：
- sources: scMM/ion/contracts.py、species.py、relations.py、hypotheses.py、representation.py、identity.py；tests 为上述 D0-D5 文件；downstream: annotation、data、workbench；extras 依实际使用最小化，不为基础质量计算引入全站可选依赖。
- 现 annotation.sources 增加 scMM/ion/annotation.py、evidence.py；tests 增加 D6/D7 文件；downstream 保留 api-lipids，并增加主计划实际新增的通用注释/API 块，不臆造已存在块。
- 新 tests/support/ions.py 映射 ion-grouping/annotation 及实际导入该构造的应用/API 块；scMM/ion/__init__.py 映射显式消费者，禁止遗漏新路径靠 UNMAPPED 兜底。
- data 涉及 H5AD/门面，workbench 涉及视图独立状态/身份，analysis 涉及输入选择/数值契约，projects 涉及原子快照，api/api-lipids 涉及边界，browser-lipids/browser-preprocessing/browser-analysis-journey 涉及实际交互；按修改路径映射运行，不能只跑领域测试就宣称链路完成。
- tests/tooling/test_test_blocks.py 加入新路径/重命名/共享文件影响验证；docs、notebook 只有其文件改动才执行相应内容检查。

执行顺序建议：先对相关旧块建立基线，再 D0；并行 D1、D2、D6 数据库/导入框架；D1/D2 汇合 D3；D4/D5 并行；D6/D7 联合迁移；最后完整合成/集成贯通；真实有效性留待用户后续使用验证。每个卡完成跑其有意义反例与受影响块；通过且未再受影响的不反复全量运行。

必要检查入口（真正修改后的执行阶段）：
- uv run --no-sync python scripts/test_blocks.py --block ion-grouping --phase python --run（新增块后）
- uv run --no-sync python scripts/test_blocks.py --block annotation --phase python --run
- uv run --no-sync python scripts/test_blocks.py --files 本里程碑实际路径（先看影响计划，再 --run）
- 单个数值诊断用 python -m pytest -q -W error；不以 -k 同名测试替代完整受影响块。

领域完成定义：所有关系类型均有正确候选、失败/不可评估/冲突行为；竞争图不强并；L1/L2 映射可复现；未知保留；通用候选及迁移完整；外部证据可导入并正确限制作用域；失败不改输入；参数来源与 pending 均明确；实际实验结论只在有相应数据时报告。

## 13. 已确认边界与唯一必填实验信息

已确认，执行代理不重复问：

1. **完整范围**：自然同位素、加合物/电荷、多聚体、碎片关系、竞争归组、L1、固定代表 L2、通用候选及外部证据导入均在计划内；碎片和多聚体关系完整实现，不等于默认合并量化。
2. **量化边界**：L2 只实现全项目固定代表离子，不做其他多离子策略；只预留契约，调用明确不支持。
3. **注释边界**：通用质量/已有分子式候选和外部证据导入；不做自动 MS/MS 谱匹配，不做从头公式枚举。现脂质候选及旧版本需兼容。
4. **实验背景**：甲醇；正离子常见 H、Na、K、NH4 和去水加氢；负离子规则完整实现并用合成数据验证，当前没有负离子真实验证。质量误差通常≤5 ppm、偶尔≤10 ppm；候选质量容差保持明确可配置，不把描述视为最优算法阈值。
5. **规模/任务方式**：每样本≤1000 cells/500 features，新增功能局部后台获授权；旧 M2 仍不恢复。领域纯函数输出可用于后台结果发布，取消/迟到结果/工作区修订由应用层处理。
6. **验证与授权**：用户暂不提供验证数据，优先功能，用户后续使用验有效性。每阶段可本地提交；最终用户验收后再 push/release。合成、真实实验、用户验收和远端 CI 分开记录。

仍必须从实际采集配置获取：**采集分辨率数值及参考 m/z/缩放定义**。不能仅据 QE 型号猜采集 resolution；字段缺失时依赖分辨能力的检查明确不可评估，保留候选与原始峰。该缺失不阻止其他无依赖开发，不把 pending 自动变为默认值。

其余数值判定策略采取明确可配置的软件规则与保守未解决状态，界面/文档说明待真实有效性验证；不向用户重新索要其已明确暂不提供的数据，也不以此将完整功能缩为同位素。新项目 L1 推荐及旧项目显式选择、singleton 记录、标准报告按具体证据断言实现；不得把未有证据的结构层级/生物来源显示成已确认。

无需反复询问：纯函数拆分、dataclass 校验、float64、稳定 ID、输出排序、质量索引、无副作用、原始数据保留、兼容读取、pending 显示、冲突保留及有意义单测。这些可按计划直接实施；执行阶段的提交、服务和发布严格遵循主计划，不另设授权流程。
