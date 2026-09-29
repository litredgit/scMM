# Thermo RAW 直接读取：分阶段记录

## 范围与确认

- 2026-09-29：用户批准 Thermo RawFileReader → C# → 二进制管道 → NumPy。
- 保留 `CyESIData.load_from_file()`；不新增 SCData 类、不改下游数学算法。
- 严格 profile；任何 centroid scan 报错，不跳过、不转换。
- 无 GUI、XIC、RAW 写入、自动 mzML 转换、复杂缓存或 scan 级并行。
- 对照为用户自行转换的同目录 `wt-1.mzML`，不安装 msconvert。
- 验证输入：`/home/crs/data/crs/data/260922/wt-1.RAW`（只读）。

## 阶段

| 阶段 | 内容 | 状态 |
|---|---|---|
| 1 | 依赖、C# reader、协议与真实文件初验 | 完成 |
| 2 | Python reader、异常和资源回收测试 | 完成 |
| 3 | 单文件/目录接入、流式对齐及回归 | 完成；见续接日志 |
| 4 | 全扫描对照、下游语义、性能和文档 | 完成；单个真实 RAW + 合成目录回归 |

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

## SCMMRAW1 协议

所有整数与 float64 均为小端，无结构体 padding；文本为 int32 字节长度 + UTF-8。

- 文件头：8 字节 magic、int32 扫描数、采集时间文本（不虚构时区）、仪器文本。
- scan：uint8=1、int32 原始编号、int32 MS level、uint8=1（profile）、
  float64 RT 秒、int32 点数、float64[点数] m/z、float64[点数] intensity。
- 结束：uint8=0、int32 实际扫描数、int64 总点数；随后 EOF 和进程退出码 0。
- stderr 仅诊断；stdout 不允许日志。缺失结束标志不算成功。
- 不排序、去重、补零、裁剪或滤波；空 profile scan 保留。

## 日志

- 初始工作树干净。验证文件存在：RAW 328 MiB、mzML 481 MiB（显示值）。
- 已检查旧路径：RAW 通过临时 mzML；对齐先收集完整 spectrum 列表。
- .NET SDK 用户目录隔离安装成功；尚未更改线上服务或主仓库。
- 阶段 1：C# Release 编译通过，0 警告/0 错误。真实 RAW 完整顺序读取：
  4,302 scans、81,059,698 points，全部 profile，无跳过扫描。
- 重要发现：RawFileReader 默认排除 reference/exception peaks。显式设置
  `IncludeReferenceAndExceptionData=true` 才能满足完整 profile，与 ProteoWizard
  官方 Thermo reader 一致。未进行峰提取、补点或数值校正；全部强度现已与 mzML 精确一致。
- 对照 mzML（ProteoWizard 3.0.25322）使用 32 位 m/z/强度。m/z 的差异全部可由
  float32 舍入解释；不降低生产 reader 的 float64 精度。
- 采集时间：RAW `2026-09-22T16:04:29.9770000`（无时区），mzML 经原读取器得到
  `2026-09-22 08:04:29`。未擅自减 8 小时；绝对时间接入等待用户确认采集时区。
- 阶段 2：20 项新增协议/清理测试通过，全量 **283 passed**（`-W error`）；ruff 通过。
  C# 无效/不存在输入实际检查退出 1、stdout 为空；缺参数退出 2。
- [读取验证报告](validation/thermo-wt-1-reader.json)：所有强度精确一致；所有 m/z
  在 float32 舍入后精确一致；单个 RT 差 `5.684341886080802e-14` 秒，其余一致。
  初测 2.558 秒，1,682 scans/s，3,169 万 points/s，进程树采样峰值 RSS 553 MiB。
  缓存未清空，RSS 包括共享/映射页；不声称厂商内部无缓存或端到端恒定内存。
- 2026-09-29 用户进一步确认：默认采集时区 `Asia/Shanghai`（显式可覆盖）；
  RAW 保留 float64，接受以现有 32 位 mzML 作量化感知验证，并单独报告下游差异。
- reader 已部署至 `/home/crs/.local/share/scmm/thermo-reader`，未改线上服务。

## 历史暂停点（2026-09-29，阶段 2）

用户因限额要求适时暂停。已验证的代码提交：

- `73d57f6`：C# reader、固定依赖与协议。
- `f1a3d28`：Python reader、20 项新测试、全扫描对照及验证脚本。

暂停时尚未切换 `CyESIData` / 目录处理；已在下方续接阶段完成切换。
底层流式入口仍可独立使用：

```python
from scMM.file.readers import ThermoRawReader

with ThermoRawReader("/home/crs/data/crs/data/260922/wt-1.RAW") as reader:
    for spectrum in reader:
        mz, intensity = spectrum.get_peaks()
        # 逐 scan 消费，不要 list(reader) 缓存整份原始谱。
```

默认从用户目录寻找部署 DLL 和 .NET；可用 `SCMM_THERMO_READER` / `SCMM_DOTNET`
指定路径。数组是只读 bytes 视图，离开上下文后仍有效；如需修改请显式复制。
reader 为单次上下文，提前退出会回收子进程。第一阶段只验证 Linux。

### 后续实施顺序

1. 添加可重新打开的 RAW source，两遍处理分别顺序读取；校验文件未在两遍之间变化。
2. 按已确认的 `Asia/Shanghai` 解释无时区采集时间，提供显式覆盖并记录来源；
   保留亚秒精度，不为匹配 mzML 而截断。现有 mzML 时间行为不变。
3. 接入实际 `CyESIData.load_from_file()`、shared/independent 目录路径；
   对齐消费迭代器，不再收集原始 spectrum；原数学算法、frame 编号、输出格式不变。
4. 清除自动 RAW→临时 mzML 路径；旧 `msconvert_path` 的迁移行为须明确记录并测试，
   不允许在 direct reader 失败时隐式回退。
5. 增加流式生命周期/两遍/下游语义测试；在真实文件上比较完整处理结果及耗时/内存。
   不将 float32 对照的差异隐藏在宽泛容差中。最后总结、分阶段提交。

阶段 3 的未验证草稿保存于 `/tmp/scmm-thermo-stage3-draft.patch`，已从工作树撤回；
它仅供续接参考，尚未覆盖目录处理、算法异常回收及兼容测试，**不能直接当成完成代码**。
即使 /tmp 被清理，也可按以上步骤重建。主仓库、5006 服务、原始数据均未修改。

### 复现验证

```bash
PYTHONPATH=. /home/crs/scMM/.venv/bin/python -m pytest -q -W error
PYTHONPATH=. /home/crs/scMM/.venv/bin/python tools/validate_thermo_raw.py \
  /home/crs/data/crs/data/260922/wt-1.RAW \
  /home/crs/data/crs/data/260922/wt-1.mzML \
  --report /tmp/scmm-thermo-new-report.json
```

验证脚本需要 psutil（本机 7.2.2），不覆盖已有报告；JSON 仅为诊断统计，不作谱图中转。
它先测 direct 读取，再加载完整 mzML 对照；当前不是下游生产验收自动放行工具。
SDK 8.0.425 与 NuGet 缓存位于 `~/.local/share/scmm/dotnet` / `nuget`；
官方包与许可保存于 `~/.local/share/scmm/thermo-packages`。重新编译使用
`dotnet restore --locked-mode`（该本地包源加官方 NuGet 源），随后 Release publish。

输入文件 SHA-256：

- RAW：`f604eeb601b3db97e947bc398ebeb2e0ad258d2322a873b0e9d5e95f1a38bff5`
- mzML：`fd2f7a7250b7c90b52c2aa9c51af9bb7f07e995a4f42de994d569373a267fa6f`

## 续接阶段 3：入口与流式处理

- 用户恢复额度后继续；确认真实文件参考离子为 **760.5847**。
  文档示例 734.5929 的尝试已停止，不作为验收参数或科学结论。
- `load_single_file()` 按扩展名分发：RAW 返回可重开的 `ThermoRawSource`，
  XML 保持原 PyOpenMS 加载行为。两者以 `get_peaks/getRT/getMSLevel` 协议供同一算法消费。
- RAW 不装入完整 MSExperiment；合谱与对齐分别重读，保留 float64；对齐只累积
  最终特征行，不累积原始谱。最终特征矩阵和厂商内部内存仍随数据规模变化。
- 所有算法迭代用上下文回收，提峰/插值异常也会关闭管道；两遍间检查文件身份、
  大小和修改时间，发现变化报错。正常流程保留零起点 frame_id，不改成厂商 scan number。
- 采集时间保留亚秒，默认 Asia/Shanghai；`raw_timezone` 参数优先于
  `SCMM_RAW_TIMEZONE` 环境变量。无效时区、夏令时重叠/缺失时间报错，不静默猜测。
- `CyESIData.load_from_filelist()` 三种策略支持 Thermo RAW 文件；不递归、不把
  `.raw` 目录当成 Thermo 文件。默认含 RAW 的 legacy 目录使用 1 个文件 worker，
  纯 XML 沿用原默认全部 CPU；显式 n_jobs 可覆盖，shared/independent 保持原串行策略。
- 不自动去重同目录的 RAW/mzML：验证对照文件不要和待批处理 RAW 混放在输入目录，
  否则会被当作两个输入。可使用仅含选定 RAW 的目录（允许文件符号链接）。
- 自动转换已移除：非空 `msconvert_path` / `--msconvert` 报迁移错误；
  `convert_raw()` 保留为手动工具，不在 reader 失败时回退。GUI 和在线服务不变。
- 新增 13 项流水线测试：合成 RAW/XML 全处理与 H5AD 往返、三种目录策略、
  编号/时区/文件变更、异常进程回收、拒绝隐式转换、确认不累积原始谱及 DST 边界。
  专项 33 项通过；全量 **296 项通过**（`-W error`），ruff 检查通过。

```python
from scMM.file.data import CyESIData

data = CyESIData.load_from_file("sample.RAW", ref_mz=760.5847, raw_timezone="Asia/Shanghai")
compatible = CyESIData.load_from_file("sample.mzML", ref_mz=760.5847)
batch = CyESIData.load_from_directory("raw_only", ref_mz=760.5847, feature_strategy="shared")
```

CLI 同样支持 `scmm-process sample.RAW results --ref-mz 760.5847
--raw-timezone Asia/Shanghai`。以上参考值是本次 wt-1 用户指定值，不是通用默认。

## 阶段 4：真实端到端验证与交付

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

### 复现端到端检查

```bash
PYTHONPATH=. /home/crs/scMM/.venv/bin/python tools/validate_thermo_pipeline.py \
  /home/crs/data/crs/data/260922/wt-1.RAW \
  /home/crs/data/crs/data/260922/wt-1.mzML \
  --ref-mz 760.5847 --report /tmp/scmm-thermo-pipeline-new.json
```

此脚本需仓库包含基线提交 9d07a2e、已安装 reader 和 psutil。临时 NPZ 只用于保存
验证矩阵，结束即清理；Git 中只保留汇总报告，不包含私人 RAW/mzML/矩阵。
任一 mzML 旧/新或量化 RAW 对照的数值断言失败，会返回非零退出码并保留报告。

### 验证边界

- 全量 296 项自动测试通过；真实测试覆盖用户提供的单个 Q Exactive 文件。
  多文件目录策略用合成 RAW 流 + 真实 mzML 测试，未做多份真实 RAW 的并发压力测试。
- GUI、Windows、其他厂商、centroid 支持、复杂缓存仍暂缓；无自动格式转换。
- 本轮没有改主仓库或部署 5006。功能已在当前 worktree 的 Python/CLI 可用；
  调用时确保使用当前源码（例如 `PYTHONPATH=.`），不要误用主仓库的可编辑安装。
