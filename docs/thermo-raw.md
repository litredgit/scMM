# Thermo RAW：运行依赖、协议与验证

[文档索引](README.md) · [安装部署](installation.md) · [Python API](python-api.md)

## 支持范围与运行行为

Thermo RawFileReader → C# helper → 二进制管道 → NumPy 已接入单文件、三种目录策略、CLI 和网页。
严格接受 profile，任何 centroid scan 报错；包含 reference/exception peaks，保留 float64，
不排序、去重、补点或自动转换。非空 `msconvert_path` / `--msconvert` 提示迁移错误，
独立 `convert_raw()` 仍是手动工具，reader 失败不隐式回退。

RAW source 可重开，合谱与对齐分别顺序读取；两遍之间校验身份、大小及修改时间。
异常或提前结束会回收子进程。对齐只累积特征行，不缓存整份原始谱；最终矩阵和厂商内部内存仍随规模增长。
保持零基 frame_id、秒制 RT；采集时间保留亚秒，以 `raw_timezone` 优先于 `SCMM_RAW_TIMEZONE`，
默认 Asia/Shanghai。无效或有夏令时歧义的时间报错。

含 RAW 的 legacy 目录默认一个文件 worker，显式 n_jobs 可覆盖；shared/independent 仍串行。
目录不递归、不将 `.raw` 目录当文件，也不自动去重 RAW/mzML 对照。网页预览同步重读 RAW，
多个 EIC 一次遍历完成，单扫描仍顺序读取到指定索引。

## 依赖与部署

- 隔离 SDK：`/home/crs/.local/share/scmm/dotnet`，.NET SDK 8.0.425。
- Thermo 包：RawFileReader / Data 8.0.42；官方仓库固定提交
  `cd0a429a9894c13cc8bc0a5a10d54f5b7eb991bb`。
- 官方来源：<https://github.com/thermofisherlsms/RawFileReader>。
- 厂商包不进入 Git；本机安装不构成对外发布。再分发/商业使用须另行核对官方
  `License.doc`，不要把厂商组件视作 scMM 自有开源代码。
- NuGet 传递依赖由 `tools/thermo_raw_reader/packages.lock.json` 锁定。
- 官方 nupkg 的 SHA-256：
  - Data：`0b1d2fff2f81532e0c56471b22bc0e2c0c6685f37aa43b0b134ad82ae75ae444`
  - RawFileReader：`af259d466e24227ba6706872330a0736d6fc2f552ad9d46a78a4697f0f62e1a6`

默认 helper 为 `~/.local/share/scmm/thermo-reader/scmm-thermo-reader.dll`，也会查找 PATH 中的
`scmm-thermo-reader`；可用 `SCMM_THERMO_READER` 指定 DLL 或可执行文件。
DLL 需要 .NET 8，优先 `SCMM_DOTNET`，其次 PATH，再到 `~/.local/share/scmm/dotnet/dotnet`。
`uv sync` 不会安装这些外部组件。

已验收环境的厂商包与许可位于 `~/.local/share/scmm/thermo-packages`，SDK/NuGet 缓存位于
`~/.local/share/scmm/dotnet` / `nuget`。重新构建先配置厂商本地包源和官方 NuGet 源，
在 `tools/thermo_raw_reader/` 使用 `dotnet restore --locked-mode`，随后 Release publish。
这些本机路径是部署记录，不保证其他机器已存在。

## 流式读取与协议

```python
from scMM.file.readers import ThermoRawReader

with ThermoRawReader("sample.RAW") as reader:
    for spectrum in reader:
        mz, intensity = spectrum.get_peaks()
        # 逐扫描消费，不用 list(reader) 缓存整份原始谱。
```

reader 是单次上下文；数组为只读 bytes 视图，退出后仍有效，修改前需复制。
`SCMMRAW1` 协议如下：

所有整数与 float64 均为小端，无结构体 padding；文本为 int32 字节长度 + UTF-8。

- 文件头：8 字节 magic、int32 扫描数、采集时间文本（不虚构时区）、仪器文本。
- scan：uint8=1、int32 原始编号、int32 MS level、uint8=1（profile）、
  float64 RT 秒、int32 点数、float64[点数] m/z、float64[点数] intensity。
- 结束：uint8=0、int32 实际扫描数、int64 总点数；随后 EOF 和进程退出码 0。
- stderr 仅诊断；stdout 不允许日志。缺失结束标志不算成功。
- 不排序、去重、补零、裁剪或滤波；空 profile scan 保留。

## 真实文件验证

2026-09-29 的 Q Exactive wt-1（4,302 scans、81,059,698 profile points）为单个真实样本证据。
[读取报告](validation/thermo-wt-1-reader.json)确认所有强度精确一致，m/z 经 float32 舍入后与
用户提供的 ProteoWizard 32 位 mzML 精确一致；单个 RT 差约 5.7e-14 秒。

阶段 3 提交：`f551542`。验证使用参考离子 **760.5847**、默认 m/z 100–1000、
分辨率 35000、legacy 细胞提取与其余现有默认参数。没有改科学算法或全局参考离子默认值。
脚本：[validate_thermo_pipeline.py](../tools/validate_thermo_pipeline.py)；
完整统计：[thermo-wt-1-pipeline.json](validation/thermo-wt-1-pipeline.json)。

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

### 网页与部署验收

[网页报告](validation/thermo-wt-1-web.json)记录同参数预览与 Python 正式处理的窗口、峰顶帧、RT
及参考信号精确一致，结果为 307 × 622；首/中/末扫描均可读，Chromium 页面脚本错误 0。
09-29 主仓库回归 301 项通过，5006 首页及 systemd reader 验收完成；后续部署摘要见
[CHANGELOG](../CHANGELOG.md)。这不代表多真实 RAW 压力测试、更多仪器或 Windows 已验收。

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

验证不作生产自动放行依据；跨仪器、批量负载及环境待办见[路线与验收](roadmap.md)。
