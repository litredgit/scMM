# 脂质注释规则预设：审阅草案 v1

检索与编写日期：2026-10-13。以下五份 JSON 可通过网页导入，也可从安装包默认提供的规则预设选择，**分值仍待审阅及实验验收**。
下表链接到安装包内的规则源文件；网页的已保存预设由应用单独管理。保存预设不会自动应用到项目，文件名和预设名称均标记为审阅草案。

| 样本 | 规则文件 | 适用范围及首要限制 |
|---|---|---|
| PBMC | [pbmc.review-v1.json](../../scMM/resources/lipid_rules/pbmc.review-v1.json) | 人外周血单个核细胞混合群体；不能代表每种免疫细胞或激活状态 |
| 人癌细胞 | [human_cancer.review-v1.json](../../scMM/resources/lipid_rules/human_cancer.review-v1.json) | 未指定癌种/细胞系时的哺乳动物膜脂及储存脂候选排序 |
| 小鼠癌细胞 | [mouse_cancer.review-v1.json](../../scMM/resources/lipid_rules/mouse_cancer.review-v1.json) | 小鼠来源癌细胞；与人癌细胞暂用相同分值，避免人为制造物种差异 |
| 藻类 | [algae.review-v1.json](../../scMM/resources/lipid_rules/algae.review-v1.json) | 光合真核藻类的宽范围草案；不假定所有藻种含同一组甜菜碱脂 |
| 大肠杆菌 | [ecoli.review-v1.json](../../scMM/resources/lipid_rules/ecoli.review-v1.json) | 常规大肠杆菌的 PE/PG/CL 优先排序；突变株/改造菌及特殊培养条件需另行审阅 |

## 如何理解和审阅分值

文献支持下文列出的脂类存在、组成差异和离子化现象；**0～30 的类别分及 0～2 的加合物分均为人工建议，文献没有验证这些分值**。
类别分表示值得优先核对的程度，不是浓度、检出率、鉴定置信度或“癌细胞特异性”。
所有分值非负，0 表示未给予额外优先权，不代表不存在。没有规则的候选也保留。
先按绝对 ppm 的 `≤2`、`>2 且 ≤5`、`>5` 档排序，再在档内比较类别分＋加合物分；同档同分保留并列、分别显示。
规则不改变质量容差、天然同位素容差、搜索加合物开关、人工选择、矩阵或导出筛选。

类别和加合物各自只采用一条最具体的命中规则，不逐层累加。例如 PBMC 的 LPC 取 15 分，覆盖 GP01 的 30 分，
而不是相加得到 45 分。两项相加后才形成 `rule_score`。代码和导入字段说明见[评分规则文件](../../docs/parameters.md#评分规则文件)。

建议先核对以下三项：五列类别分的相对顺序；具体细胞系/藻种/菌种是否需要分支；采集溶剂和盐是否支持相应加合物。
这些文件可先审阅，采用时在网页选择已保存预设或导入文件，预览后运行/应用；也可修改后另存命名预设。
规则预览支持分页核对全部条目，不只显示前 50 项。

## 类别分完整对照

下表列出全部非通用类别条件。`—` 表示没有该层级规则，实际取通用回退分；不是删除候选。
类别分对正、负模式相同，离子化偏好另外由加合物分表达，避免把生物组成与离子响应混为一项。

| level / value | 含义 | PBMC | 人癌 | 小鼠癌 | 藻类 | 大肠杆菌 |
|---|---|---:|---:|---:|---:|---:|
| MAIN_CLASS / GP01 | PC 家族，含醚脂、溶血类等 | 30 | 30 | 30 | 20 | 0 |
| MAIN_CLASS / GP02 | PE 家族 | 30 | 30 | 30 | 20 | 30 |
| MAIN_CLASS / GP03 | PS 家族 | 25 | 25 | 25 | 10 | 10 |
| MAIN_CLASS / GP04 | PG 家族 | 10 | 15 | 15 | 30 | 25 |
| MAIN_CLASS / GP06 | PI 家族 | 25 | 25 | 25 | 15 | 0 |
| MAIN_CLASS / GP10 | PA 家族 | 10 | 15 | 15 | 15 | 15 |
| MAIN_CLASS / GP12 | 心磷脂 CL 家族 | 10 | 15 | 15 | 10 | 20 |
| MAIN_CLASS / GP13 | CDP-甘油脂中间体 | — | — | — | — | 10 |
| MAIN_CLASS / SL01 | 酰基氨基糖，含 lipid A 相关结构 | — | — | — | — | 10 |
| MAIN_CLASS / SL02 | 酰基氨基糖聚糖 | — | — | — | — | 5 |
| MAIN_CLASS / SP02 | 神经酰胺家族 | 15 | 20 | 20 | — | — |
| MAIN_CLASS / FA01 | 脂肪酸及结合物 | 15 | 15 | 15 | 15 | 15 |
| MAIN_CLASS / GL02 | 二酰/二取代甘油家族 | 10 | 20 | 20 | 15 | 10 |
| MAIN_CLASS / GL03 | 三酰/三取代甘油家族 | 10 | 20 | 20 | 20 | 0 |
| MAIN_CLASS / GL04 | 糖基单取代甘油 | — | — | — | 10 | 0 |
| MAIN_CLASS / GL05 | 糖基二取代甘油 | — | — | — | 15 | 0 |
| MAIN_CLASS / GL06 | 甜菜碱单取代甘油 | — | — | — | 10 | — |
| MAIN_CLASS / GL07 | 甜菜碱二取代甘油 | — | — | — | 20 | — |
| MAIN_CLASS / ST01 | 甾醇家族 | — | — | — | 10 | — |
| SUB_CLASS / ST0101 | 胆固醇及衍生物 | 5 | 5 | 5 | — | — |
| LIPID_CLASS / LPC | 溶血 PC | 15 | 15 | 15 | 10 | 0 |
| LIPID_CLASS / LPE | 溶血 PE | 15 | 15 | 15 | 10 | 10 |
| LIPID_CLASS / LPG | 溶血 PG | 5 | 10 | 10 | 10 | 10 |
| LIPID_CLASS / LPI | 溶血 PI | 10 | 10 | 10 | 5 | 0 |
| LIPID_CLASS / LPS | 溶血 PS | 10 | 10 | 10 | 5 | 5 |
| SUB_CLASS / SP0301 | 鞘磷脂 SM（含缺缩写的记录） | 25 | 25 | 25 | — | — |
| LIPID_CLASS / HexCer | 单己糖神经酰胺 | 10 | 15 | 15 | — | — |
| LIPID_CLASS / CE | 胆固醇酯 | 10 | 20 | 20 | — | — |
| LIPID_CLASS / MGDG | 单半乳糖二酰甘油缩写 | — | — | — | 30 | — |
| LIPID_CLASS / DGDG | 双糖二酰甘油缩写 | — | — | — | 30 | — |
| LIPID_CLASS / SQDG | 磺基奎诺糖二酰甘油 | — | — | — | 30 | — |
| LIPID_CLASS / SQMG | 磺基奎诺糖单酰甘油 | — | — | — | 15 | — |
| LIPID_CLASS / DGTS | 二酰甘油三甲基高丝氨酸脂 | — | — | — | 25 | — |
| LIPID_CLASS / DGTA | DGTA 甜菜碱脂 | — | — | — | 25 | — |
| LIPID_CLASS / DGCC | DGCC 甜菜碱脂 | — | — | — | 25 | — |

通用回退规则：五份文件均有八大 `CATEGORY`（FA、GL、GP、SP、ST、PR、SL、PK）的显式条目。
GP 一律 5 分；PBMC/人癌/小鼠癌的 GL、SP 也为 5 分；其余均 0 分。未知分类同样默认 0 分。
没有单独给外源药物、培养基成分、色素或复杂信号脂加分，并不表示这些候选不存在。

## 加合物分完整对照

五份文件共用同一套 **50 条**加合物规则，避免未经证据就把人/鼠/菌种直接映射为盐偏好。
其中 8 条为所有受支持加合物的全局 0 分回退，另 42 条为下表的类别条件。
每份文件同时支持正、负模式；网页选中的极性及加合物决定实际搜索范围。

| 类别条件 | polarity | H | Na | K | NH4 | 说明 |
|---|---|---:|---:|---:|---:|---|
| MAIN_CLASS / GP01、GP02；SUB_CLASS / SP0301 | pos | 2 | 1 | 1 | 0 | PC/PE/SM 常见质子化形式优先核对；此顺序需结合实际 CyESI 条件审阅 |
| MAIN_CLASS / GL01、GL02、GL03；LIPID_CLASS / CE、MGDG、DGDG | pos | 0 | 1 | 1 | 1 | 中性脂类的阳离子加合物保守并列，不假定 NH4 高于 Na/K |
| 其余 | pos | 0 | 0 | 0 | 0 | 没有足够通用证据，不附加排序偏好 |

上表 H、Na、K、NH4 分别对应 `[M+H]+`、`[M+Na]+`、`[M+K]+`、`[M+NH4]+`。

| 类别条件 | polarity | [M-H]- | [M+Cl]- | [M+HCOO]- | [M+OAc]- |
|---|---|---:|---:|---:|---:|
| MAIN_CLASS / GP02、GP03、GP04、GP06、GP10、GP12、FA01；LIPID_CLASS / SQDG、SQMG | neg | 2 | 0 | 0 | 0 |
| MAIN_CLASS / GP01；SUB_CLASS / SP0301 | neg | 0 | 1 | 1 | 1 |
| 其余 | neg | 0 | 0 | 0 | 0 |

Na、K、NH4 的并列及三个负离子加合物的并列表示**尚无依据细排**，不表示它们实际响应相等。
NH4、Cl、甲酸根和乙酸根的来源须依据采集配方/样本实际情况判断；本草案没有替你设定溶剂、盐、pH 或浓度。
即使规则给予某加合物加分，也不会自动开启该离子的搜索。采用前可把不适用的项改为 0，并在网页中关闭其搜索。

类别分最小常用间距为 5，加合物分最大为 2；这样加合物只在相近类别证据下帮助排序。
例如 PBMC 同一 ppm 档中 PC/H 为 32 分、PC/Na 为 31 分、SM/H 为 27 分。
不同 ppm 档仍先比较档位，不能靠 30 分类别分越过更好的 ppm 档。

## 文献依据及不能推出的结论

以下均链接到原始研究或 LIPID MAPS 官方资源；这里只概括与规则相关的证据，具体分值是本项目的推断。

1. **分类对应**：[LIPID MAPS 脂类分类](https://www.lipidmaps.org/data/classification/LM_classification.php?category=3)。
   使用官方层级及本地 SDF 的字段/ID 核对匹配代码；CL 对应 GP12，GP05 不能当作 CL。
   CE 使用具体缩写，避免将 ST0102 的全部植物甾醇酯也作为哺乳动物胆固醇酯加分。
2. **PBMC**：[Kuliszkiewicz-Janus 等，2005，正常人 PBMC 的磷脂组成](https://pubmed.ncbi.nlm.nih.gov/16217549/)。
   人 PBMC 提取物中观察到 PC、PC 缩醛磷脂、LPC、SM、PE、PI、PS、CL，支持常见膜脂先核对。
   研究使用群体提取及磷谱，不支持本草案的单细胞分值、全部中性脂优先级或某种加合物响应。
3. **PBMC 状态差异**：[New Insights on the PBMCs Phospholipidome in Obesity，2021](https://pmc.ncbi.nlm.nih.gov/articles/PMC8541295/)。
   该原始研究讨论肥胖和糖代谢状态相关磷脂变化；这里只据此保留状态限制，不把某一疾病组的变化当作 PBMC 固有排序。
4. **人癌细胞**：[Comprehensive Lipidome Profiling of Isogenic Primary and Metastatic Colon Adenocarcinoma Cell Lines，2012](https://pubs.acs.org/doi/abs/10.1021/ac302154g)。
   SW480/SW620 的磷脂、鞘脂、中性脂存在明显组成差异，支持保留 TG、CE、Cer、醚脂等候选。
   这不能推出所有癌种均 TG/CE 增高；论文也展示 PC/H、PE/H、PA/NH4 的等质量歧义，一级质量和排序无法确认结构。
5. **小鼠癌细胞**：[Péter 等，2012，B16 小鼠黑色素瘤细胞的营养脂供应研究](https://pubmed.ncbi.nlm.nih.gov/22583025/)。
   血清脂供应和培养密度可改变膜脂组成，支持保留哺乳动物共同脂类并避免根据“鼠源”捏造独立链长/不饱和度规律。
   小鼠草案与人癌草案暂同分，二者分开保存以便后续按细胞系分别修订。
6. **小鼠膜脂补充证据**：[Hishikawa 等，2008，B16 细胞的 PC/PE/PS 重塑实验](https://pubmed.ncbi.nlm.nih.gov/18287005/)。
   用作 PC/PE/PS 候选存在和可重塑的证据，不将酶干预后的变化推广为未处理肿瘤的固定比例。
7. **藻类**：[Nannochloropsis PJ12 的磷限制脂质组研究，2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6780086/)。
   覆盖 MGDG、DGDG、SQDG、PG、PC、PE、DGTS 及储存脂，且营养状态改变脂类组成。
   据此提高光合膜脂优先级，并保留磷脂/甜菜碱脂/TG；不为所有藻种规定相同比例或营养状态。
8. **红藻及离子形式**：[da Costa 等，2017，Gracilaria 脂质组](https://pubmed.ncbi.nlm.nih.gov/28257116/)。
   提供糖脂、磷脂和甜菜碱脂的原始鉴定证据；[文中离子表](https://pmc.ncbi.nlm.nih.gov/articles/PMC5367019/)报告 MGDG/DGDG 铵加合及 SQDG/SQMG 脱质子形式。
   该 HILIC-MS 条件不直接等同于本项目的 CyESI；这里只作为小幅离子化偏好的依据。
9. **DGCC 的条件性**：[Hunter 等，2018，Thalassiosira pseudonana 磷胁迫研究](https://journals.asm.org/doi/10.1128/aem.02034-17)。
   DGCC 在该研究的磷胁迫条件下出现，正常供磷组未检出；提高其候选优先级不意味着所有藻类均应出现 DGCC。
   DGTA 同样只保留为可能的藻类甜菜碱脂候选，其与 DGTS/DGCC 同分是保守兼容选择，尚无本样本的细排证据。
10. **大肠杆菌膜脂**：[Hines 与 Xu，2019，磷脂合成缺陷的 HILIC-IM-MS 脂质组研究](https://pmc.ncbi.nlm.nih.gov/articles/PMC6438183/)。
    原始研究覆盖 PE、PG、CL，以及少量 LPE、LPG、酰基 PG 和 N-酰基 PE；支持优先核对 PE/PG/CL，并保留代谢中间体。
    草案 PE/PG/CL 分别为 30/25/20，体现常规膜脂优先级，不能将文献群体丰度直接换算为单细胞检出率。
    PC、PI、TG 和糖基甘油脂不再沿用宽泛细菌的加分；0 分仍完整保留候选，不排除改造菌或外源成分。
11. **大肠杆菌状态与外膜边界**：[Genetic evidence for functional diversification of gram-negative intermembrane phospholipid transporters，2024](https://journals.plos.org/plosgenetics/article?id=10.1371/journal.pgen.1011335)。
    原始实验显示突变/温度条件可改变 PG/CL 组成，不能将 30/25/20 当作恒定丰度关系。
    [LipidA-IDER 原始研究](https://pubs.acs.org/doi/10.1021/acs.analchem.1c03566)支持保留外膜 lipid A 相关候选，但一级质量不能确认其结构，当前也不新增多电荷模型。
12. **通用加合物偏好的边界**：[Bishop、Shen、Fiehn，2023，Evaluating Adduct Formation](https://escholarship.org/content/qt16g954ws/qt16g954ws.pdf)。
    DAG 加合物分配随基质、结构和仪器条件变化，支持保留多加合物及不为 Na/K/NH4 强制细排。
    文中的加合物合并定量不作为本项目求和依据；本项目仍只排序和标记、保留各测量峰。
13. **方法相关的质子化证据**：[Software tool for internal standard based normalization of lipids，2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6489209/)。
    比较了 Na 加合物和方法中主要的质子化/中性脂铵加合形式；据此给出小幅化学偏好，不能解释为跨方法固定的主峰响应。

## 数据库覆盖与适用边界

- 已按本机 LMSD 的有效质量记录核对分类条件。核对库 SHA-256：
  `f77d752c487bdcc97c07c6711e0f69c9021b0e3954584ceb72253f388b222512`；数据库文件不在此文件夹，也不入 Git。
- `LIPID_CLASS` 依赖 SDF 中的缩写；缺少缩写的条目会取较粗分类回退分。
  本库部分条目分类字段与历史 LM_ID 前缀有差异；当前匹配器两者均识别，分值不能修复数据库分类歧义。
- 大肠杆菌草案不采用金黄色葡萄球菌的 LysylPG 优先规则，也不将整个 FA08 一律高分。
  其他细菌研究中的 DGDG 可指不同己糖头基；相同缩写/一级精确质量无法区分葡萄糖与半乳糖或其他异构结构。
- 不根据链长、双键数、支链、奇偶碳链或单个分子名称打分；这些需要明确物种/培养条件，而且当前规则接口没有这类条件字段。
- 当前模型限于受支持的标准单电荷加合物；未覆盖 `[M+H-H2O]+`、二价 CL、聚集离子等；大肠杆菌 CL 若主要以二价离子采集，本规则不能补齐这部分注释。
  未发现某种脂类不能直接解释为样本中不存在，尤其自由胆固醇和需要其他离子形式的脂类。
- 文献多数采用群体提取或 LC/ESI-MS，与 CyESI 的基质和电离条件不同；本任务只校验文件/排序兼容性，不声称实验鉴定准确率。

五份规则随安装包提供为默认可选预设，原始 JSON 统一维护在 `scMM/resources/lipid_rules/`。新环境无需导入；仍须主动选择并运行/应用排序。同名用户预设优先保留原保存值。
