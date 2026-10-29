# 测试职责与检查入口

[任务导航](README.md) · [架构职责](development.md)

## 完整验证

日常本地检查运行修改及受影响块；自动 CI 使用同一计划的轻量配置，手动 CI 执行完整配置。先看计划，再执行；没有修改且不受影响的块跳过。
逐块整理时先对准备修改的块建立基线，修改后验证该块与受影响部分；已经通过且后续未受影响的块不重复运行，
不在结束时默认再跑全量。`-W error` 继续将警告作为错误。

```bash
# 默认比较 HEAD 与暂存区/工作区，并纳入未跟踪文件；只输出计划
uv run --no-sync python scripts/test_blocks.py
# 执行计划中的检查（使用已同步的开发环境）
uv run --no-sync python scripts/test_blocks.py --run
# 比较完整提交范围；本地 feature 分支可将 --base 指向共同祖先
uv run --no-sync python scripts/test_blocks.py --base origin/dev --head HEAD
# 显式指定块，不混入当前工作区的其他改动；适用于逐块基线与验证
uv run --no-sync python scripts/test_blocks.py --block spectra --phase python --run
# 只查看指定文件的影响，不需要实际修改文件
uv run --no-sync python scripts/test_blocks.py --files frontend/src/features/monitor/MonitorPage.vue
```

唯一映射为 [`tests/blocks.json`](../tests/blocks.json)，选择器为
[`scripts/test_blocks.py`](../scripts/test_blocks.py)。每次输出选择、原因和跳过的块；
`--write-plan` 保存计划，`--plan` 复用同一份计划，`--phase` 只执行其中一个阶段。
`--files` 可提供明确的文件集合，`--block` 可重复。移动文件同时检查旧/新路径，不能只看重命名后的路径。
选择器使用目录/文件列表与显式依赖关系，不使用全局 `-k`。

### 测试目录与块

```text
tests/
  support/       # 显式导入的小型谱、项目、脂质与认证/HTTP 构造
  domain/        # 数值定义、数据容器、RAW/XML、统计、注释与绘图
  application/   # 参数、预览/提取、持久任务、项目、回收和结果生命周期
  api/           # HTTP 请求、权限、修订、下载及必要贯通检查；局部 conftest
  tooling/       # 发布/回滚、扫描、快照、选择器、文档与 Notebook
  blocks.json    # 本地/CI 共用的文件 → 块及依赖方映射
frontend/tests/  # fixtures.ts、server.py 和按交互划分的 spec
```

| 块 | 保障范围 |
|---|---|
| `spectra` | 谱 I/O、峰/细胞、SNR、ppm、RAW 协议/资源回收与 RAW/XML 等价 |
| `data` | 矩阵/元数据、合并、H5AD/旧目录、原子写入、归一化及零分母 |
| `analysis` | 统计、分组验证、监督诊断、统一降维 |
| `annotation` | 质量候选、同位素、规则、数据库下载/完整性 |
| `plotting` | Notebook 绘图、轨迹、趋势及网页显示精度 |
| `processing` | 原始预览、参数、缓存、持久 worker、提取审核、质量产物及处理 CLI |
| `projects` | 项目/快照、恢复起点、修订冲突、路径与回收保护、UTF-8 持久边界 |
| `workbench` | 变换事务、结果失效、历史层与潜变量持久化 |
| `time` / `api-time` | 时间应用输入/依赖/登记、只读重载及 HTTP 修订、权限和下载身份 |
| `api` / `api-raw` / `api-lipids` | 工作区/样本/分析/保存下载、原始谱与提取、脂质 HTTP 契约 |
| `auth` / `monitor` | 认证/服务器配置及管理员监控 |
| `tooling` | 发布阻塞与回滚、扫描、上游快照、跨平台导入与分块选择 |
| `docs` / `notebook` | 受影响文档的链接/锚点与 Python 示例；Notebook 清洁及语法 |
| `browser-*` | 项目、工作流/分析、导航、登录/普通 HTTP、监控、脂质及 AI；实际 spec 与影响范围以 blocks.json 为准 |

两批次比较的只读、ID/输入身份、摘要损坏与旧版证据边界在 `test_project_batch.py` 和 `test_web_api.py`；
项目内清理在 API 与 saved-items/retention 块验证未保存及跨项目引用保护。
浏览器 workflow 保留两批信号联动与清理贯通，raw 验证真实拖动、复位再缩放、完整范围导出及旧标签/用户输入区分，
analysis 验证三维视角导出和集中设置；这些仍是隔离合成检查。

数值断言集中领域层，应用层验证失败/恢复和生命周期，API 验证边界/序列化/状态，浏览器保留真实交互。
不同边界不能只因功能同名而删除；共享构造从 `support` 导入，不从另一个测试文件导入。
根目录不放通用重型 fixture，HTTP 工作流 fixture 只在 `tests/api/conftest.py` 注册。

### 选择规则与 CI

- 测试文件变化只运行其所属块；共享 fixture 变化只运行实际使用它的块，不扩展到业务依赖方。
- 业务源码变化按映射扩展到使用者；公共数据层、接口/工作区契约、依赖锁文件会扩大范围，并输出原因。
- 纯前端变化不运行 Python 测试；按功能选浏览器 spec。共享组件、路由、状态/客户端及前端依赖会影响全部浏览器块。
  Prettier 配置单独变化只检查前端格式，不运行构建或浏览器测试；格式规则/前端依赖变化时检查全部前端格式输入。
- 文档变化只检查相关文档；链接目标变化同时检查引用它的文档。文档检查器本身改变时检查全部维护文档。
  Notebook 独立成块，普通 Markdown 改动不执行 Notebook 检查，更不执行其中的实验代码。
- 已知目录中的新文件若缺少细分映射，明确报告 `UNMAPPED` 并选择该区域的保守范围；其他未知路径报错，须补映射。
  不能静默当作无影响，也不把每次常规改动都退回全量。

自动 CI 在 dev/main push 与 PR 触发，Python 版本为部署一致的 3.12；保留公开支持范围，
3.11 在依赖/兼容性改动时本地验证，手动 `workflow_dispatch` 完整检查同时运行 3.11/3.12。
`changes` 只计算一次计划：PR 比较 merge-base→head，push 比较 before→after；首次 push 检查全部输入。
main 快进仅包含 dev 已有提交时跳过重复检查，main 独有提交继续检查；这不表示 dev 失败检查自动通过。
每次 push 保留各自区间的轻量检查，不以较新提交取消旧检查，避免连续推送文档时漏掉前一实现区间。
比较失败直接失败，不能当作无改动。

自动配置 `--lightweight` 保留相关文档/链接、改动 Python Ruff/格式与源码扫描；前端按需格式和类型检查，
不自动构建前端、运行浏览器或发行包。业务/构建改动的少量干净环境冒烟为选择器及服务器配置测试，
仅安装锁定 base/dev/web，不依赖本地前端产物。配置测试显式 `static_root=None`，
生产缺少静态资源仍须明确拒绝启动；不能以配置测试替代正式启动或浏览器测试。

本地与手动完整配置保留原有 Python、浏览器、前端构建、发行包及产物扫描阶段。
本地日常先运行相关块；里程碑按改动补共享边界、主要浏览器和发行包。
发行包包含静态资源，打包前构建前端；测试或 Markdown 单独变化不构建发行包。
查看自动配置可使用 `python scripts/test_blocks.py --files 路径 --lightweight`，
`--write-plan` / `--plan` 保证本地与 CI 执行同一选择结果，不维护第二套测试列表。

浏览器自动启动 5117 的隔离服务，使用临时项目和合成数据，不访问开发或生产实验。
通用夹具在同一 worker 内复用合成账号认证，避免大套件耗尽地址登录预算；每例仍新建浏览器上下文和工作区。
显式退出/撤销后重新登录，认证与不安全 HTTP 专项保留独立真实登录流程，不更改服务认证限制。
`SCMM_E2E_PORT`、`SCMM_TEST_PYTHON`、`SCMM_CHROMIUM` 可指定端口、解释器与已有浏览器；
`SCMM_TEST_STATIC_ROOT` 可显式指向本次已验证的暂存 Vite 资源；未指定时，隔离服务启动时在临时目录新建资源，
单个 spec 不读取仓库历史构建。共用入口整轮运行时复用该轮刚完成的构建；独立浏览器阶段自动临时构建。
首次浏览器执行前安装依赖及 Chromium：

```bash
npm --prefix frontend ci
npm --prefix frontend exec -- playwright install chromium
```

截图、trace 和报告保留在被忽略的测试输出目录。普通 HTTP 用例的浏览器显式隔离继承的代理变量，固定测试域映射至本地；代理返回的 502 不能归为元素等待假失败。
Linux Chromium 仍需系统动态库和字体，缺库属于浏览器未启动，不能记为页面断言失败。
合成检查不替代真实实验、用户验收或远端 CI。
原始预览使用独立进程、提取使用持久 worker；其余 HTTP 计算持有工作区锁。
`/api/v1/runtime` 的未保存/繁忙工作区与页面活动证据继续约束发布，不因测试分块而放松。

### 手动全量入口

仅在明确需要完整检查时执行；日常修改和本轮整理不默认执行：

```bash
uv run --no-sync python scripts/test_blocks.py --all --run
# 只运行全部 Python 测试并统计覆盖率
uv run --no-sync python -m pytest -W error --cov=scMM --cov-report=term-missing
```

单文件诊断仍可使用 `uv run --no-sync python -m pytest tests/domain/test_data.py -q -W error`。
从仓库根使用 `python -m pytest`，确保本地 `scripts` 与 `tests.support` 可导入。
依赖同步、真实 RAW 对照及规模检查按实际改动单独执行，不作为每次运行的隐含前置。

## 脂质注释规模检查

网页领域计算在 `util/lipid_annotation.py` / `lipid_isotopes.py`，声明式规则在 `lipid_rules.py`；
数据库下载、摘要及加载在 `application/lipid_database.py`，事务/版本/审阅/导出在 `web_lipids.py`，
严格 HTTP 契约在 `api/lipid_schemas.py`，页面组件在 `frontend/src/features/preprocess/LipidPanel.vue`。
不通过任意函数执行接口，不改变 `CyESIData.deisotope()` 的原有算法或默认值。

质量搜索对数据库排序索引二分查找，仅对匹配的母峰/理论同位素/观测特征计算关系；
质量/同位素搜索不构造特征平方矩阵。相关网络在 `util/lipid_network.py` 按样本使用临时特征平方相关矩阵，
只对绘图阈值以上或化学关系对计算共同检出相关；审阅感知的饼图/分子映射/显示投影在 `lipid_network_views.py`。
节点显示上限不减少辅助证据计算，完整候选包括同质量异构记录，公式分布缓存复用，不以截断候选节省资源。
按用户确认，本轮限于 ≤500 特征的同步请求，不开展 M1/M2；不能据此宣称其他重任务已后台化。

合成规模报告可在数据库已准备的环境复现：

```sh
python tools/benchmark_lipid_annotation.py --cells 3000 --samples 10 --features 500 --output /tmp/lipid-3000.json
python tools/benchmark_lipid_annotation.py --cells 10000 --samples 10 --features 500 --output /tmp/lipid-10000.json
```

输出仅为参数/规模/耗时/进程峰值内存与数量，不保存矩阵。实际报告见
[3,000 × 500](validation/lipid-annotation-synthetic-3000x500.json)和
[10,000 × 500](validation/lipid-annotation-synthetic-10000x500.json)。耗时分开记录数据库首次加载与领域计算，
峰值内存包含解释器、数据库、矩阵和工作区输入副本，不等于单个算法数组占用；尚不包含完整 HTTP 保存流程峰值。
用户选择手动验收，不以这些合成结果声明真实样本准确率。

相关网络的当前合成规模证据另见
[3,000 × 500 网络报告](validation/lipid-network-synthetic-3000x500.json)和
[10,000 × 500 网络报告](validation/lipid-network-synthetic-10000x500.json)。复用上述命令并更换输出文件名可复现；
本次领域总耗时包含相关网络，报告新增两层边对数、化学关系数和注释版本 JSON 大小。
图表/网络模块在安装包内，版本数据随 H5AD/项目保存；前端不持有矩阵或执行化学判定。

专项检查为 `tests/domain/test_lipid_annotation.py`、`tests/api/test_web_lipids.py` 和 `frontend/tests/lipids.spec.ts`，
覆盖双侧比例边界、加合物组成、并列/重复质量、失败原子性、版本/预设、过期下载及保存重载；
浏览器使用本地合成 SDF，不访问或下载真实数据库，也不打开用户项目。

## Notebook 检查

通用 notebook 应满足：

- 所有用户路径和实验参数集中在参数单元。
- 不包含个人主目录绝对路径。
- 提交前清除大量执行输出和临时图。
- 参数单元带 `parameters` 标签，便于 Papermill 等工具注入配置。
- 示例默认值不执行不可逆或高风险步骤。
- 文档中说明无法仅凭示例默认值确定的实验参数，尤其是 `REF_MZ`。

基本结构和语法检查可以在没有科学计算依赖时完成：

```bash
uv run --locked python -m json.tool scMM_workflow.ipynb >/dev/null
uv run --locked python - <<'PY'
import ast
import json

with open("scMM_workflow.ipynb", encoding="utf-8") as handle:
    notebook = json.load(handle)

for number, cell in enumerate(notebook["cells"]):
    if cell["cell_type"] == "code":
        ast.parse("".join(cell["source"]), filename=f"cell-{number}")
print("notebook syntax OK")
PY
```

这不能代替在 uv 管理的项目环境中使用代表性 mzML 执行整个流程。


## 场景隔离与失败归属

| 层 | 必要检查 | 起点与依赖 |
|---|---|---|
| 领域 | 数值定义、算法边界、维度、有限值 | 小型确定性输入；不启动 HTTP/浏览器 |
| 应用 | 编排、候选事务、失败恢复、结果生命周期 | 每例构造新数据/项目；时间公共构造在 `tests/support/time_analysis.py`，不共享可变矩阵 |
| API | 参数、权限、修订、序列化与下载身份 | 临时认证/项目和局部 HTTP fixture；不要求前端先构建 |
| 浏览器 | 真实操作反馈、异步竞态及少量贯通 | 每例独立 context/工作区；认证仅同 worker 复用；不依赖前例页面或构建残留 |
| 工具 | 文档、选择器、构建/发布脚本 | 临时 Git/资源目录；缺少映射显式失败或保守报告 |

原 `workflow.spec.ts` 的混合场景分成 preprocessing、storage、raw、operations 与 analysis-journey，
保留 workflow 的独立 worker 提取→人工审核→分析贯通。预处理应用/reset 与分析导出/重载各自导入输入，
单独运行不借用前一场景状态。轮询/请求代次及导出竞态归 operations，原始谱诊断归 raw。
时间应用按命名结果/Palantir、速度和趋势分文件；精确数值算法仍主要由领域 trajectory 测试维护。
脂质 useLipid* 只选脂质浏览器块，时间适配器只选 time/api-time 与实际浏览器使用者；
数据层、工作区、公共模式及 PlotView 变更继续扩大共享回归。

失败先按证据区分产品断言、测试夹具/起点耦合、环境依赖和基础设施。
浏览器等待超时应检查 trace、请求和页面反馈，不默认认定为假失败；不吞错、无界重试或统一扩大超时。
旧 CI 配置测试的构建依赖与修复见[历史结论](../CHANGELOG.md#第二至第三节点一致性安全与分析能力完善)。
