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
| 2 | Python reader、异常和资源回收测试 | 待执行 |
| 3 | 单文件/目录接入、流式对齐及回归 | 待执行 |
| 4 | 全扫描对照、下游语义、性能和文档 | 待执行 |

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
