# 验证报告

[文档导航](../README.md) · [如何复查](../development.md#专项验证与复现) · [开发历史与用户验收](../../CHANGELOG.md)

## 真实文件对照

Thermo wt-1 的[读取](thermo-wt-1-reader.json)、[处理链](thermo-wt-1-pipeline.json)和[网页预览](thermo-wt-1-web.json)均以同一个历史样本为范围。对照基线、参数和硬件见下节。离子归组和二级证据的真实样本验证仍见[待办](../development.md#未完成事项与恢复条件)。

## 合成与工程验证

| 报告 | 范围 |
|---|---|
| [离子工程规模](ion-engineering.json) | 搜索完成状态、资源、完整快照和回读 |
| [脂质注释 3,000 × 500](lipid-annotation-synthetic-3000x500.json) · [10,000 × 500](lipid-annotation-synthetic-10000x500.json) | 数据库加载、质量候选与同位素计算 |
| [脂质网络 3,000 × 500](lipid-network-synthetic-3000x500.json) · [10,000 × 500](lipid-network-synthetic-10000x500.json) | 相关计算、边对、保存体积和资源 |
| [网页批次检查](web-batch-20261019.json) | 该版本的网页批次与环境核验 |

## 来源与发布核验

[LMSD 来源记录](lmsd-20261019.json)保存当次数据库下载和文件摘要。[开源审阅记录](open-source-audit.json)保存当次源码与发布检查。实际用户验收依开发历史对应版本记录。

## Thermo wt-1 对照与复现

2026-09-29 的 Q Exactive wt-1（4,302 scans、81,059,698 profile points）为单个真实样本证据。
[读取报告](thermo-wt-1-reader.json)确认所有强度精确一致，m/z 经 float32 舍入后与
用户提供的 ProteoWizard 32 位 mzML 精确一致；单个 RT 差约 5.7e-14 秒。

对照实现基线：`f551542`。验证使用参考离子 **760.5847**、默认 m/z 100–1000、
分辨率 35000、legacy 细胞提取与其余现有默认参数。没有改科学算法或全局参考离子默认值。
脚本：[validate_thermo_pipeline.py](../../tools/validate_thermo_pipeline.py)；
完整统计：[thermo-wt-1-pipeline.json](thermo-wt-1-pipeline.json)。

| 路径 | 耗时 | 进程树采样峰值 RSS | 对齐矩阵 | 最终细胞矩阵 |
|---|---:|---:|---:|---:|
| RAW 直接读取，float64 | 93.89 s | 685 MiB | 4302 × 5192 | 307 × 622 |
| 现有 32 位 mzML，新流式对齐 | 91.83 s | 1661 MiB | 4302 × 5196 | 307 × 622 |
| 现有 mzML，9d07a2e 旧对齐 | 93.35 s | 2819 MiB | 4302 × 5196 | 307 × 622 |

每条路径使用独立 Python 进程；包含文件读取、合谱、提峰、对齐和细胞提取，
不包含事先生成 mzML 的转换耗时。10ms RSS 采样包含共享/映射页及相同的验证矩阵副本，
不等于独占物理内存；缓存未清空，单次测量不作速度承诺。收益主要是降低内存并移除中转文件。

### 精确性与已知差异

- **mzML 行为保持**：新旧对齐的特征轴、完整对齐矩阵、最终细胞矩阵、细胞帧和 RT
  均精确相等；不是仅比较形状。
- **编码差异归因通过**：验证脚本单独启用 float32 RAW 量化后，特征轴、完整矩阵及
  细胞矩阵与用户提供 mzML 精确相等；唯一的单 scan RT 序列化差仍为约 5.7e-14 秒。
  量化只在验证脚本中，不进入生产 reader，也不生成临时 mzML。
- **生产 RAW 与 32 位 mzML 并非逐项相等**：两者细胞数、最终特征数、细胞帧和细胞 RT
  相同，但完整选峰分别为 5192/5196 个。最终特征中心也存在偏移，不能仅按列位置
  将两条结果混为同一特征轴。
- 最终 622 个特征中，采用仅用于诊断的 1 ppm 双向最近邻匹配，有 621 对可匹配；
  这些共同特征 × 307 个共同细胞中，16 个强度元素不同，最大绝对差 192354.171875。
  该差异不被宽泛容差抹掉，也不宣称对所有下游分析无影响；完整的 float32 复现实验
  支持其来自输入编码差异。按用户决定，生产路径仍保留 float64。
- RAW 绝对采集时间已按 Asia/Shanghai 解释；在本机 UTC 环境中与 XML 相差 0.977 秒，
  原因为 RAW 保留亚秒而 XML/OpenMS 对照只到整秒。原始时刻与所用时区都记录在来源中。
- 原始 4,302 个 scan、81,059,698 个 profile 点均保留；读取层强度精确匹配对照，
  reference/exception peaks 明确包含。下游仍执行原有合谱/提峰/细胞处理，不应混淆为 reader 在做 centroid。

### 网页预览数值对照

[网页报告](thermo-wt-1-web.json)记录同参数预览与 Python 正式处理的窗口、峰顶帧、RT
及参考信号精确一致，结果为 307 × 622；首/中/末扫描均可读，Chromium 页面脚本错误 0。
运行环境及部署验收记录见 [CHANGELOG](../../CHANGELOG.md#第一至第二节点工程化与完整工作台迁移)。
该单样本对照不代表多真实 RAW 压力测试、更多仪器或 Windows 已验收。

### 复现

安装 reader 及验证脚本依赖 psutil（历史验证为 7.2.2），从仓库根目录运行；报告使用新路径：

```bash
uv run --locked --with psutil==7.2.2 python tools/validate_thermo_raw.py \
  /path/to/wt-1.RAW /path/to/wt-1.mzML --report /tmp/scmm-reader-new.json
uv run --locked --with psutil==7.2.2 python tools/validate_thermo_pipeline.py \
  /path/to/wt-1.RAW /path/to/wt-1.mzML \
  --ref-mz 760.5847 --report /tmp/scmm-pipeline-new.json
```

端到端脚本需要 Git 基线 `9d07a2e`；临时 NPZ 只存验证矩阵，结束清理，Git 仅保留汇总报告。
数值断言失败返回非零状态并保留报告。输入 SHA-256：

- RAW：`f604eeb601b3db97e947bc398ebeb2e0ad258d2322a873b0e9d5e95f1a38bff5`
- mzML：`fd2f7a7250b7c90b52c2aa9c51af9bb7f07e995a4f42de994d569373a267fa6f`

适用范围是该历史样本的读取与处理对照。现有真实样本验证待办见[当前规划](../development.md#未完成事项与恢复条件)。
