# 文档与任务导航

首次了解项目见[根 README](../README.md)。开发默认只读[根规则](../AGENTS.md)和下表对应主题；
跨模块时再沿调用、数据及状态依赖追查。无需每次通读历史或全部开发指南。
当前行为见主题文档，未来事项见[roadmap](roadmap.md)，历史只见[CHANGELOG](../CHANGELOG.md)。

## 按任务阅读

| 任务 | 代码入口 | 必读文档 | 对应测试/块 |
|---|---|---|---|
| 原始读取、细胞检测、RAW | `scMM/file/io.py`、`file/readers/`、`util/peak.py` | [细胞识别](cell-feature-identification.md)、[RAW](thermo-raw.md)、[参数](parameters.md) | `tests/domain/`：spectra；`tests/api/test_raw_extraction.py` |
| 提取审核、预览与任务 | `scMM/application/processing.py`、`project_batch.py`、`tasks.py` | [操作](workflow.md)、[参数](parameters.md) | `tests/application/`：processing；api-raw；browser-workflow |
| 变换、元数据、合并与保存 | `scMM/file/data.py`、`application/workbench.py`、`projects.py`、`processed_merge.py` | [数据格式](data-output.md)、[Python API](python-api.md) | data、projects、workbench；`test_merge_api.py` |
| 统计、监督、降维 | `scMM/analysis/`、`application/workbench.py`、`frontend/src/features/analysis/` | [分析](analysis.md)、[功能接入](feature-development.md) | analysis、workbench、api；`frontend/tests/analysis.spec.ts` |
| 时间与趋势 | `scMM/application/time_analysis.py`、`scMM/plot/_trajectory.py` | [时间方法](time-analysis.md)、[结果格式](data-output.md) | `test_trajectory.py`、`test_time_analysis.py`、`test_time_api.py` |
| 脂质候选、规则与审核 | `scMM/util/lipid_*.py`、`application/web_lipids.py`、`frontend/src/features/preprocess/LipidPanel.vue` | [脂质方法](lipid-analysis.md)、[规则依据](../rules/lipids/README.md)、[参数](parameters.md) | annotation、api-lipids、browser-lipids |
| 绘图、显示与导出 | `scMM/plot/`、`frontend/src/components/PlotView.vue` | [分析绘图](analysis.md)、[格式](data-output.md)、[交互](workflow.md) | plotting、`frontend/tests/interface.spec.ts`；共享组件按映射扩大 |
| 认证、监控、AI | `scMM/application/auth.py`、`monitor*.py`、`ai_*.py` | [架构边界](development.md)、[安装配置](installation.md) | auth、monitor、ai 及对应浏览器块 |
| 测试、映射与 CI | `tests/blocks.json`、`scripts/test_blocks.py`、`.github/workflows/ci.yml` | [测试指南](testing.md) | `tests/tooling/test_test_blocks.py`、test_environments.py |
| 发布、回滚、上游来源 | `scripts/scmm_env.py`、`scripts/import_upstream_snapshot.py` | [发布指南](release.md)、[安装配置](installation.md) | tooling；发行包检查 |
| 文档维护 | 根及 `docs/` Markdown | [维护职责](../AGENTS.md#文档职责与更新时机) | `tests/tooling/test_documentation.py` |

## 主题职责

- [工作流](workflow.md)维护操作顺序；[参数](parameters.md)维护默认值、单位、范围与算法选项。
- [Python API](python-api.md)维护公开调用；[数据格式](data-output.md)维护保存、恢复和互操作。
- [分析](analysis.md)、[脂质方法](lipid-analysis.md)、[时间方法](time-analysis.md)维护方法含义与限制。
- [开发指南](development.md)维护架构；[功能接入](feature-development.md)维护扩展契约；[测试](testing.md)维护检查入口；[发布](release.md)维护运维与来源。
- [安装](installation.md)维护环境与配置；[排错](troubleshooting.md)按症状定位；[原始验证报告](validation/)保存独有证据。
