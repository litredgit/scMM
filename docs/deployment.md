# 部署与运维

[文档导航](README.md)

本页供服务器管理员。首次安装先同步锁定环境，再准备资源与账号，最后启动网页。运行 Thermo profile RAW 需另行部署 reader。已有服务器按[发布、更新与回滚](#发布更新与回滚)操作。

[部署网页](#网页服务部署) · [Thermo RAW](#thermo-raw-额外依赖) · [发布与回滚](#发布更新与回滚) · [监控](#管理员监控) · [存储清理](#存储清理与自动保留) · [排错](#部署与运维排错)

## 推荐方式：uv

先按 [uv 官方安装说明](https://docs.astral.sh/uv/getting-started/installation/) 安装 uv，然后在仓库
根目录同步完整环境：

```bash
uv sync --locked --all-extras --dev
```

uv 会读取 `.python-version`，在需要时安装 Python 3.12，并根据 `uv.lock` 创建项目专用 `.venv`。
项目会以可编辑模式安装，修改本地 `scMM/` 后无需重新安装。不要再用 pip 向 `.venv` 手工添加
长期依赖；发布依赖通过 `uv add` 管理，开发工具通过 `uv add --dev` 管理。

当前正式支持 Python 3.11–3.12。项目把 PyOpenMS 和核心数值栈限制在本机及 CI 已验证的兼容
范围；PyOpenMS 3.3 没有 CPython 3.13 wheel，因此在新 PyOpenMS 版本通过部署机器的 CPU、原始谱
读写和完整测试前，不应只为追新版本移除这些上限。

日常拉取代码后重复上述同步命令，严格复用锁文件。
只有明确升级依赖时才运行 `uv lock --upgrade`，并将 `pyproject.toml` 与 `uv.lock` 的变更一起审阅、
测试和提交。`uv sync` 默认精确同步，会移除未声明的包，因此临时工具优先使用 `uvx` 或
`uv run --with <package>`。

## Thermo RAW 额外依赖

mzML/mzXML 使用 Python 环境中的 PyOpenMS。直接读取 Thermo profile RAW 还需要
.NET 8 和已部署的 Thermo RawFileReader helper；`uv sync` 不安装这些外部组件。
当前真实验收在 Linux，其他厂商 RAW 和 Windows 实机未验收；centroid scan 会报错。

reader 默认查找用户目录中的部署文件，也可用 `SCMM_THERMO_READER`（DLL 路径）和
`SCMM_DOTNET`（运行程序路径）指定。采集时区默认 `Asia/Shanghai`，可通过
`raw_timezone` / `SCMM_RAW_TIMEZONE` 覆盖。依赖版本、构建步骤、部署路径和验证证据见
[构建 reader](#构建与配置-reader)、[RAW 协议](internal-reference.md#流式读取与协议)和[真实文件对照](validation/README.md#thermo-wt-1-对照与复现)。不会在直接读取失败时自动转换 mzML；
旧 `--msconvert` / `msconvert_path` 参数及手动转换模块已移除。

### 构建与配置 reader

- 隔离 SDK：`~/.local/share/scmm/dotnet`，.NET SDK 8.0.425。
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

## 依赖分组

| 分组 | 主要用途 |
|---|---|
| 核心依赖 | 原始谱读取、矩阵处理、保存、归一化、基础统计 |
| `plot` | Matplotlib/Seaborn、UMAP、Palantir 和轨迹图 |
| `cluster` | Leiden 与 Louvain 聚类 |
| `supervised` | 监督学习、SMOTE 和 SHAP |
| `web` | FastAPI/Uvicorn、Plotly、Matplotlib、NetworkX、UMAP 及兼容依赖；Vue 构建工具由 npm 单独管理 |
| `dev` 依赖组 | pytest、Ruff、构建与覆盖率；不进入发布包依赖 |

仅运行核心处理可使用：

```bash
uv sync --locked --no-dev
```

按需启用功能，例如：

```bash
uv sync --locked --extra plot --extra cluster
uv sync --locked --extra web
```

网页 Palantir 另需 `plot` 可选依赖：`uv sync --locked --extra web --extra plot`。
仅安装 `web` 时仍可使用窗口轨迹；Palantir 缺失会明确报错，不改用其他算法。

完整交互开发环境可使用 `uv sync --locked --all-extras --dev`。PR 验证按
[受影响测试块](development.md#选择规则与-ci)安装需要的 extras，仍共享同一份锁文件，不默认安装 Notebook 工具链。

## 验证安装

```bash
uv run --locked python -c "import scMM, pyopenms, anndata; print('scMM environment ready')"
uv run --locked scmm-process --help
uv run --locked scmm-web --help
uv run --no-sync python scripts/test_blocks.py --block data --phase python --run
```

如果入口不存在，先运行 `uv sync --locked --all-extras --dev`，并确认命令从包含 `pyproject.toml`
的仓库目录执行。

## 系统资源建议

原始目录处理会构建公共 m/z 网格，并可能并行读取多个谱文件。建议：

- 先用单个文件和 `N_JOBS=1` 验证参数。
- 再把 `N_JOBS` 增大；`-1` 会使用所有可用 CPU。
- 内存不足时减少并发，而不是优先降低质量分辨率。
- 将结果写到本地高速磁盘，完成后再归档到网络存储。

## 网页服务部署

### Vue/FastAPI 网页

仓库前端位于 `frontend/`，要求 Node.js 22.12+；本项目 CI 使用 Node.js 24。
Python 和前端分别使用 `uv.lock`、`frontend/package-lock.json` 固定依赖。仓库环境中执行：

```bash
uv sync --locked --all-extras --dev
npm --prefix frontend ci
npm --prefix frontend run build
uv run --locked scmm-web --server-config ~/.config/scmm/dev.json --port 5007
```

`scmm-web` 是唯一网页命令；旧 `scmm-ui`、`--frontend` 与 `--allow-websocket-origin` 已移除。
静态资源构建到 `scMM/api/static/`，与 `/api/v1` 接口由同一个服务提供；运行服务不需要 Node 进程。
服务器资源和实验参数独立配置，启动前须完成下节初始化。网页按钮只能选择已授权根目录内的文件，不能新增根目录。

### 服务器初始化与账号

真实配置、认证数据库、监控数据库、一次性凭据和运维令牌均放在 Git 工作区之外，认证和监控数据库还必须位于网页可浏览目录之外。
仓库的 [服务器模板](../config/server.example.json) 只展示通用字段，不含真实路径或凭据。
管理员在服务器终端执行一次初始化，原始数据目录必须已经存在；初始化显式创建输出及运行目录，不覆盖已有配置或数据库：

```bash
uv run --locked scmm-admin --server-config ~/.config/scmm/dev.json init \
  --admin admin \
  --auth-db ~/.local/state/scmm/dev/auth.sqlite3 \
  --storage "原始数据=/srv/scmm/raw" \
  --project-root ~/.local/state/scmm/dev/results \
  --preferences ~/.local/state/scmm/dev/preferences.json \
  --cache-root ~/.local/state/scmm/dev/cache \
  --temp-root ~/.local/state/scmm/dev/tmp \
  --recycle-root ~/.local/state/scmm/dev/recycle \
  --cookie-name scmm_dev --insecure-cookie --port 5007
uv run --locked scmm-web --server-config ~/.config/scmm/dev.json
```

上例用于可信内部 HTTP 环境；`--insecure-cookie` 是显式例外。默认 Cookie 要求 HTTPS。
仍沿用内部 HTTP 的生产实例也须显式设置该例外；公网开放前必须完成 HTTPS 并恢复 Secure 标记。
本阶段不包含公网反向代理、TLS 或公网开放。开发与生产分别初始化，使用不同配置、认证数据库及 Cookie 名；
同主机不同端口不会隔离 Cookie。普通启动不提问、不生成管理员、不创建缺失的必需目录、不回退匿名。

初始化将 24 小时内有效的一次性凭据写入配置同目录的 `.initial.txt` 文件，将运维令牌写入 `.operations-token` 文件，
均为 600 权限；终端只显示文件位置。首次登录消耗初始化凭据，设置 15–128 字符密码后用新密码登录。
管理员可在“账号与管理”创建账号、重置密码、启停账号和查看最近安全记录；重置结果只返回一次。
每次进入该页都会刷新团队账号，列表包含已停用的账号。读取失败时可在表格旁重新读取。
改密、重置、停用立即撤销相应登录会话；不能停用最后一个管理员。无法登录时在服务器终端恢复：

```bash
uv run --locked scmm-admin --server-config ~/.config/scmm/dev.json reset-password admin \
  --credential-file ~/.config/scmm/admin-recovery.initial.txt
uv run --locked scmm-admin --server-config ~/.config/scmm/dev.json rotate-operations-token
```

凭据文件不要提交、截图或放进项目目录。数据库只保存 Argon2id 密码哈希和随机会话令牌摘要；
账号资料与会话独立于项目快照，项目重载不会恢复旧登录权限。

### 访问与路径配置

配置优先级为 **命令行 > 环境变量 > 本地资源配置 > 通用默认值**。
资源配置文件由 `--server-config`、`SCMM_SERVER_CONFIG`、`~/.config/scmm/server.json` 依次选择；显式选定的文件不存在即报错。
`--config` / `SCMM_UI_CONFIG` 仍仅管理实验参数，格式见[参数参考](extraction.md#网页默认参数与适用范围)。

| 资源 | 命令行 | 环境变量 | 资源配置字段 |
|---|---|---|---|
| 监控数据库 | `--monitor-db` | `SCMM_MONITOR_DB` | `monitor_db` |
| 自动保留数据库（可选） | `--retention-db` | `SCMM_RETENTION_DB` | `retention_db` |
| 环境标识 | `--environment` | `SCMM_ENVIRONMENT` | `environment`（dev/prod/standalone） |
| 生产只读检查 | `--monitor-peer-url` / `--monitor-peer-token-file` | `SCMM_MONITOR_PEER_URL` / `SCMM_MONITOR_PEER_TOKEN_FILE` | `monitor_peer_url` / `monitor_peer_token_file` |
| 认证数据库 | `--auth-db` | `SCMM_AUTH_DB` | `auth_db` |
| 原始目录映射 | 重复 `--storage 名称=路径` | `SCMM_STORAGE_ROOTS`，JSON 对象 | `storage` |
| 项目输出 | `--project-root` | `SCMM_PROJECT_ROOT` | `project_root` |
| 其他结果目录映射 | 重复 `--output 名称=路径` | `SCMM_OUTPUT_ROOTS`，JSON 对象 | `output` |
| 全局预设 | `--preferences` | `SCMM_PREFERENCES` | `preferences` |
| 回收区/缓存/临时目录 | `--recycle-root` / `--cache-root` / `--temp-root` | `SCMM_RECYCLE_ROOT` / `SCMM_CACHE_DIR` / `SCMM_TMP_DIR` | `recycle_root` / `cache_root` / `temp_root` |
| 注释数据库 | `--lipid-database-dir` | `SCMM_LIPID_DATABASE_DIR` | `lipid_database_dir` |
| RAW helper / .NET | `--thermo-reader` / `--dotnet` | `SCMM_THERMO_READER` / `SCMM_DOTNET` | `thermo_reader` / `dotnet` |
| 监听地址/端口 | `--address` / `--port` | `SCMM_ADDRESS` / `SCMM_PORT` | `address` / `port` |
| Cookie 名/HTTPS 标记 | `--cookie-name` / `--cookie-secure` / `--no-cookie-secure` | `SCMM_SESSION_COOKIE` / `SCMM_COOKIE_SECURE`，后者为 JSON 布尔值 | `cookie_name` / `cookie_secure` |
| 允许来源 | 重复 `--origin` | `SCMM_ALLOWED_ORIGINS`，JSON 列表 | `origins` |
| 启用插件 | — | `SCMM_ENABLED_PLUGINS`，JSON 列表 | `enabled_plugins` |
| 空闲/最长会话秒数 | `--session-idle-seconds` / `--session-absolute-seconds` | `SCMM_SESSION_IDLE_SECONDS` / `SCMM_SESSION_ABSOLUTE_SECONDS` | `session_idle_seconds` / `session_absolute_seconds` |

外部 Nginx 反代时，管理员在仓库外资源配置 `origins` 中填写浏览器实际访问来源（含协议及非默认端口），
例如 `https://scmm.example.org`；外层 TLS 和后端 HTTP 的来源不同，不能仅依赖后端请求地址。
配置列表与后端直连同源地址共同生效，仍保留客户端标记、认证与 CSRF 校验；不通过通配来源或盲目信任代理头放开访问。

认证数据库、监控数据库、原始目录和项目输出无可用默认值，必须显式配置；其他通用默认值见模板。
启动检查必需目录及写权限；注释数据库、RAW helper 和 .NET 在使用对应功能时检查，不自动换到其他位置。
原始目录只暴露显式白名单，不再自动添加 `~/data`；`--isolated-storage` 仅兼容旧命令。
路径读取继续检查真实路径及符号链接，浏览器只能选择已授权范围。网页关闭 pickle 导入，旧格式请离线转换为 H5AD。
默认监听 `127.0.0.1`，代理头信任关闭；允许来源为空时只接受当前同源，填写时必须是含协议的完整来源。

Windows 完整安装和后台任务未验收，当前项目网页使用 Linux；缺少 fcntl 的最小兼容不代表完整 Windows 支持。

### 启用插件

`enabled_plugins` 默认为 `[]`。相关网络、监督与 SHAP、伪时间与趋势随 scMM 提供，可分别用 `network`、`supervised`、`time` 启用。
例如在对应服务器资源配置中添加 `"enabled_plugins": ["network", "time"]` 即可在重启后使用这两组功能。
已有项目的数据、有效报告与图仍可读取和下载。监督与 SHAP 使用 `supervised` 依赖组，Palantir 使用 `plot` 依赖组。

需要自定义主体方法时，先将审阅过的插件安装到该服务的 Python 环境，再把包声明的入口 ID 加入同一列表。
由环境管理脚本更新时，在服务器配置旁放置该环境的插件清单。配置为 `dev.json` 时清单为 `dev.plugins.json`，生产配置同理。清单示例中的文件名和摘要须替换为实际审核的 wheel。

```json
{
  "schema_version": 1,
  "wheels": [
    {
      "file": "wheels/lab_methods-1.2.0-py3-none-any.whl",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
    }
  ]
}
```

同步和发布使用当前环境清单。生产发布成功后记录该版本使用的 wheel，回滚优先使用目标版本的记录。发布失败时按上次成功发布的记录恢复。脚本先核对 wheel 摘要，待锁定的 scMM 环境同步后，离线安装清单中的包并检查依赖。相对路径以清单目录为准。新增依赖须与 scMM 锁定环境兼容，可把已审阅的依赖 wheel 一并列入清单。管理员监控中的「方法插件」显示已配置的入口、加载状态、版本及失败原因。
方法的输入、输出、交互和版本见[主体方法插件协议](method-plugins.md)。

## 个人 AI 配置

网页的 `web` 运行依赖包含 `httpx` 和 `cryptography`。管理员在仓库外初始化独立数据库与
Fernet 主密钥，开发和生产各自执行、使用不同文件；此命令不会重启服务，也不会写入项目结果目录：

```bash
uv run scmm-admin --server-config ~/.config/scmm/dev.json init-ai \
  --ai-db ~/.local/state/scmm/dev/ai.sqlite3 \
  --ai-key-file ~/.config/scmm/keys/dev-ai.key
```

初始化拒绝覆盖已有文件，数据库和主密钥分别保存为 `0600`，不能位于 Git 工作区或网页可浏览目录中。
服务器配置字段为 `ai_db`、`ai_key_file`，对应环境变量 `SCMM_AI_DB`、`SCMM_AI_KEY_FILE`；两者须同时配置。
未配置时科学工作台仍可使用，个人 AI 功能显示未启用；显式配置失效时启动报错，不另建密钥或回退明文。
按既有更新检查核对页面、未保存工作区和任务后重启对应服务。
请分别备份数据库和主密钥；丢失主密钥后无法解密旧 Key，须让用户重新保存个人配置。

默认目标限 HTTPS 公网 443 端口。每次调用重新解析 DNS，要求全部地址为公网地址，连接固定到已检查的 IP，
TLS 使用原始主机名验证；不使用环境代理、不跟随重定向。默认不会访问本机、私网、链路本地或云元数据地址。
确需内网/本机模型或其他端口时，管理员在对应服务器 JSON 的 `ai_private_urls` 中写入**完整 API 根地址**，
例如 `http://127.0.0.1:8000/v1`；只放行该协议、主机、端口及路径，不是网段或通配符。
环境变量 `SCMM_AI_PRIVATE_URLS` 为 JSON 列表；留空为 `[]`。请只放行可信模型服务。

用户在[我的账号](projects-and-data.md#ai-分析助手)保存地址、模型和新 Key；配置按登录用户隔离，
不允许管理员通过网页读取别人的 Key。代理仅发送 Chat Completions 文本请求，不支持工具或模型执行接口。
请求连接超时 10 秒、读取空闲超时 30 秒、整轮上限 180 秒，测试上限 40 秒；每账号同时仅一个 AI 请求，
不自动重试。停止/断开会关闭上游连接；上游计费及数据留存由所选服务商决定。

## 开发与生产分离

本机保留原仓库作为开发 worktree，新增相邻的生产 worktree，共享 Git 对象和原始输入。
`develop` 已更名为 `dev`，`refined` 等历史分支保留。两套虚拟环境分别按同一份 `uv.lock`
同步；生产使用 `--all-extras --no-dev`，开发使用 `--all-extras --dev`。

| 配置 | 生产 | 开发 |
|---|---|---|
| 分支 / 目录 | `main` / `~/scMM-prod` | `dev` / `~/scMM` |
| Python 环境 | `~/scMM-prod/.venv` | `~/scMM/.venv` |
| 端口 / 用户级服务 | 5006 / `scmm-ui.service` | 5007 / `scmm-dev.service` |
| 原始输入（仅引用） | `~/data` | 同左 |
| 项目、分析结果及旧任务输出 | `~/data/results`（保留已有项目） | `~/.local/state/scmm/dev/results` |
| 缓存 / 临时文件 | `~/.local/state/scmm/prod/cache` / `prod/tmp` | `~/.local/state/scmm/dev/cache` / `dev/tmp` |
| 全局预设 | `~/data/results/.scmm-preferences.json` | `~/.local/state/scmm/dev/preferences.json` |

已有部署的回收区约定为 `~/data/results/recycle`；新部署由 `recycle_root` 明确指定，需要服务用户可读写；
项目根、缓存、预设和临时目录仍分别隔离；这些是部署目录约定，实际资源值由仓库外配置指定。回收及清空操作见[网页指南](projects-and-data.md#保存和离开)。
自动保留策略与最近运行记录默认保存在各环境项目根的 `.scmm-retention.sqlite3`，可用 `retention_db` 明确指定仓库外、不可浏览的本地持久路径；父目录须已存在。
CIFS 等共享盘可能不支持 SQLite 文件锁，项目仍可留在共享盘，数据库须选择支持 SQLite 的本地磁盘，并按开发/生产隔离。指定路径失败时报错，不自动切换或创建父目录。
已有策略迁移须在服务停止后备份并完整复制数据库，不能用空库代替；备份包含所配置路径。策略按项目 ID 和启用管理员授权隔离，
默认无启用规则；备份项目根时保留此环境管理数据库，不把它当缓存清理。服务保持单进程、一个串行自动保留线程。
正常停止会等当前归档到达安全检查点，维护暂存/更新检查会阻止跨越正在运行或无法核实的清理。
异常退出的运行不会自动重放，检查回收区并处理后重新审阅启用；详情见[持续自动保留](#存储清理与自动保留)。

项目内的预览缓存、批次状态和快照随各自的项目根隔离。启动器为同步工具设置 `XDG_CACHE_HOME`、
`UV_CACHE_DIR`、`NUMBA_CACHE_DIR`、`MPLCONFIGDIR` 和 `TMPDIR`，网页再应用资源配置中的缓存/临时目录，后台 worker 继承生效值。
原始数据根沿用现有挂载，其中的生产结果子目录仍可被浏览，但开发保存和任务输出固定写入开发根；
不自动复制、迁移或清理已有结果。直接调用 Python API/Notebook 时仍应明确指定开发结果路径。
.NET/Thermo helper 是独立的共享外部依赖，不由分支切换或回滚管理。

统一入口为 [scripts/scmm_env.py](../scripts/scmm_env.py)，管理脚本使用 Linux 的 Python 3.10+ 标准库、
Git、uv、systemd 和 `ss`；包含 Vue 源码的版本同步时还需 Node.js/npm 构建前端，服务运行不启动 Node。
scMM 本身仍使用 `.venv` 中的 Python 3.12。
配置默认由上述路径推导；可在 `~/.config/scmm/environments.json` 覆盖
`dev`、`prod`、`raw`、`prod_results`、`state`、`address`，或用管理脚本的 `--config` 指定文件。该部署布局配置与网页资源配置是不同文件。
`dev_server_config` / `prod_server_config` 分别指向初始化后的资源配置，默认位于 `~/.config/scmm/dev.json` / `prod.json`。
开发和生产均通过 `scmm-web` 启动 Vue；用户级服务名称继续为 `scmm-dev.service` / `scmm-ui.service`。
已有配置中的 `dev_frontend: "vue"`、`prod_frontend: "vue"` 和 `origins` 可读取但不再参与启动，
可从配置中移除；指定其他前端会明确报错。网页实际监听地址由资源配置决定，部署布局中的旧 `address` 不再覆盖它。公网开放已由用户确认完成，状态见
[阶段记录](../CHANGELOG.md#第二至第三节点一致性安全与分析能力完善)；实际访问范围以服务器配置为准。
稳定启动器更新后仅支持含 `scmm-web` 的 Vue 版本；如需回滚更早的网页入口，须同时恢复其匹配的启动器。
`/runtime` 要求管理员会话或专用运维令牌；发布脚本从生产资源配置旁的 `.operations-token` 文件读取令牌。
凭据缺失、运行状态不可读、响应格式错误均拒绝重启，不把认证失败视为空闲。配置与运行数据不提交到 Git。不同用户/机器先创建对应 worktree，再安装服务：

```sh
# 当前仓库为 dev；生产 worktree 尚未创建时执行
# git worktree add -b main ../scMM-prod dev
python3 scripts/scmm_env.py install
```

`install` 备份原 service 文件，安装两个用户级 unit，并启用生产服务随用户管理器启动；
开发服务按需启动，不默认启用。稳定启动器复制到 `~/.local/share/scmm/scmm_env.py`，
新启动器要求对应 worktree 支持认证配置；回滚到认证之前的版本时须恢复匹配的启动器。管理脚本变化后重新执行 `install`，先完成两套资源初始化。
安装 unit 不自动重启现有进程。

启动器与新安装的 unit 启用 `PYTHONUTF8=1`，worker 继承该设置。不能只依赖 `LANG`：
本机 PyOpenMS 导入会将原生 locale 切换为 `C`。项目 JSON、全局预设和缓存元数据仍显式使用 UTF-8。
已有服务可通过用户级 drop-in 添加 `[Service]` / `Environment=PYTHONUTF8=1`，
在保存并关闭相关页面、确认无活动任务后执行 daemon-reload 和重启；不要修改已有项目文件的编码。

## 脂质数据库

网页注释使用管理员配置的 `lipid_database_dir`，也可通过命令行或 `SCMM_LIPID_DATABASE_DIR` 覆盖。
未配置或目录失效时明确报错，不切换到其他目录；
服务用户需有读取权限，缺库自动下载时还需写权限和访问 LIPID MAPS 官方 HTTPS。
该目录只接受本地普通 SDF 文件，HTTP 文件名不能越界或引用符号链接；不允许客户端指定任意下载 URL。

本地缺库时下载 [LMSD 标准 SDF](https://lipidmaps.org/databases/lmsd/download)，先写临时目录、校验压缩包/SDF，
再发布按 SHA-256 命名的文件与来源记录。已有有效库复用，不自动追踪最新版本，不覆盖损坏文件。
数据库需有 EXACT_MASS/FORMULA；无效质量记录统计后跳过，缺失/无效分子式的质量候选仍保留并记录分布诊断。
各项目保存实际数据库摘要及完整搜索结果，重载审阅/下载无需重新连接官网。

评分预设保存为 `SCMM_PREFERENCES` 所在目录的 `lipid-rules.json`，沿用开发/生产预设隔离；
安装包默认提供五份可选审阅草案；同名用户预设优先保留，不追溯修改旧项目。参数、导入格式和流程见
[网页参数](annotation.md#脂质查库与同位素参数)与[工作流程](annotation.md#查库版本与注释图表)。

## 日常开发与调试

```sh
cd ~/scMM
python3 scripts/scmm_env.py sync dev
systemctl --user start scmm-dev.service
# 访问 http://服务器地址:5007
journalctl --user -u scmm-dev.service -f
```

修改代码后执行 `systemctl --user restart scmm-dev.service`。需要终端日志、断点或临时调试时，
先停止开发 service，再前台启动；Ctrl+C 停止，修改后重新运行：

```sh
systemctl --user stop scmm-dev.service
python3 scripts/scmm_env.py serve dev
```

调试器选择 `~/scMM/.venv/bin/python`。需要 Python 断点时运行
`python3 scripts/scmm_env.py serve dev --debug`，再用 IDE 连接本机 `127.0.0.1:5678`；
它在调试器接入后才启动网页，远程开发可通过 SSH 转发该调试端口。
开发同步/更新要求 5007 已停止，避免运行期间替换依赖。其他进程手工指定生产结果路径不受启动器约束。
历史合成项目与浏览器证据保留原目录，见 [CHANGELOG 检验记录](../CHANGELOG.md#第一至第二节点工程化与完整工作台迁移)；
若需要在 5007 复用，须显式导入或复制到开发根，不把真实生产项目作为调试写入目标。

## 发布、更新与回滚

用户确认验收通过后，将本任务实现、文档和已有验证结论放入同一任务提交；
CHANGELOG 在该提交中记录用户验收通过，提交即标志开发验收完成。
随后连续完成推送、生产部署、健康检查和 `main` 推送，无需部署后再次人工验收。
发布结果通过聊天和仓库外运维记录反馈，不为补写提交号、部署状态或验收记录追加提交。
开发验收完成与生产发布成功分别反馈；发布失败须如实报告，确需修正代码或文档时才追加修复提交。

发布授权见[协作约定](../AGENTS.md#协作约定)。先完成[分块验证](development.md#完整验证)。发行包内容有变化时，用本次构建的 wheel 在受支持的独立环境中检查 `scmm-web --help` 与 `scmm-admin --help`；提取或读取链变化时，补跑相应格式的端到端验证。

在开发目录中使用同一个脚本：

```sh
# 发布：先完成开发验证及用户验收，再提交、推送 dev，发布到 main / 5006
# git add <本任务文件>
# git commit -m "feat: ..."
git push origin dev
python3 scripts/scmm_env.py release

# 更新开发：先停止 5007；拉取 origin/dev 并锁定同步，不自动启动
systemctl --user stop scmm-dev.service
python3 scripts/scmm_env.py update dev

# 更新生产：拉取 origin/main、同步依赖、重启及检查 5006
python3 scripts/scmm_env.py update prod

# 回滚到上次部署前的代码；也可指定一个已知提交或标签
python3 scripts/scmm_env.py rollback
# python3 scripts/scmm_env.py rollback <提交或标签>

python3 scripts/scmm_env.py status
```

发布/更新只接受干净 worktree，并用 fast-forward 更新 `main`；分支分叉须先在开发环境处理。
发布前执行 [开发验证](development.md#完整验证)。脚本串行锁定环境操作，自动执行下述部署优先维护，
不再要求项目关闭、未保存工作区清零、失联页面人工确认或浏览器 TCP 连接清零。
正式写入安全结束、相关计算进程退出后才停止服务并变更代码及依赖。新进程通过 systemd 状态和首页 HTTP 检查后，
`release` 才推送远端 `main`；网络推送失败时，本地新服务已生效，修复网络后补推即可。
依赖同步或健康检查失败时，脚本尝试恢复原提交、锁定依赖和服务；若恢复本身失败，按错误和日志处置，
原提交仍保存在 `refs/scmm/recovery`。脚本不会替用户完成科学验收，也不替代发布前测试。

回滚将本地 `main` 指针恢复到指定版本，并在 `refs/scmm/previous` 保存切换前版本；
不强推远端，不删除或恢复项目结果。再次 `rollback` 可切回刚才的版本，
`update prod` 会重新部署远端 `main`。回滚后的新版本发布仍须包含远端 main 的历史，避免非快进推送；
永久撤销应在 `dev` 中提交修复后正常发布。保存格式若已变化，须另外评估旧代码读取新项目的兼容性。

常规 `release`、`update prod` 和 `rollback` 使用同一部署优先策略，适用于单人或多人：

1. 通知在线页面，给予 **60 秒**保存宽限期；暂停新计算，允许已有项目保存。后台任务先请求当前样本结束后停止。
2. 宽限期后，识别本环境 worker 及其子进程，先终止、10 秒后强制结束，再验证退出；最多追加等待 5 秒。
   已完成样本保留，未完成批次记为 interrupted，旧 CLI 任务按既有契约记为 failed，不自动重放或纳入不完整结果。
3. 正式保存和其他受保护请求须安全结束；未知写请求默认受保护。最多等 120 秒，仍不能核实时中止本轮发布。
   自动保留/归档任务仍须到达安全检查点。监控失联/旧请求记录本身不充当正在写入的证据。
4. **120 秒**内逐工作区尽力暂存并验证。每工作区估算和编码产物上限 **512 MiB**，本轮累计产物预算 **1 GiB**；
   繁忙、超限、失败或超时的临时状态记录后跳过，成功包按用户/工作区独立加密验证。超时编码不能迟到发布 current 指针。
5. 停止服务后更新。systemd 使用 `KillMode=control-group`、30 秒停止上限，HTTP 请求优雅退出上限 15 秒；
   新服务最多用 120 秒恢复可用会话，失败的独立隔离，启动健康检查等待最多 150 秒。

维护包不代替主动保存项目；未保存矩阵、图和页面草稿可能丢失，正式项目仍采用完整快照与原子发布。
浏览器重连后刷新前端并恢复所属用户的可用工作区，显示本账号恢复结果。管理员可读取维护状态及配置旁 recovery 目录中的
`deployment-report.json`、`deployment-release.json`、`deployment-restore.json` 查看暂存、任务中断及恢复结果；报告仅含操作身份和原因码，不含科学矩阵或凭据。

发布客户端仅在本机使用：以服务账号读取私有认证数据库，为已完成初始化的管理员创建审计会话，最长 10 分钟且结束立即撤销。
权限来自本机私有配置/认证库的访问权；不会扩大只读 operations token 的权限，也不输出浏览器凭据。
首次更新不支持新入口的旧服务时，客户端使用既有管理员维护入口收集，尝试完整暂存；失败则按本策略记录临时状态损失，
停服后隔离未验证指针，不伪造页面关闭确认或监控空闲证据。旧服务仍有受保护请求时拒绝停止。
旧版仍可能缺少维护界面通知或自动重连，升级后生效；首次更新需按实际报告核对恢复情况。

账号页的严格维护为可选流程，继续要求页面草稿齐全和完整暂存验证；真实关闭事实仍可通过带范围/期限的关闭审阅登记。
已启动的严格收集需先取消再切换部署维护，不混用两种恢复承诺。
HTTP 200 不能代替网页操作或真实实验验收。可查看服务及具体运行目录：

```sh
systemctl --user status scmm-ui.service scmm-dev.service --no-pager
systemctl --user show scmm-ui.service -p ExecStart -p WorkingDirectory -p MainPID
journalctl --user -u scmm-ui.service -n 30 --no-pager
```

仅修改 Python 代码不需 daemon-reload；重新安装 unit 时脚本会执行 daemon-reload。


### 监控初始化与生产只读检查

新建服务器时 `scmm-admin init` 同时创建独立的 600 权限监控 SQLite，默认位于认证数据库同目录的 `monitor.sqlite3`，
也可用 `init --monitor-db` 显式指定；`init --environment dev|prod|standalone` 标识对应环境，生产须指定 `prod`。已有认证配置须先执行一次迁移命令，再更新对应服务；普通启动不自动初始化或切换数据库：

```bash
uv run --locked scmm-admin --server-config ~/.config/scmm/dev.json init-monitor \
  --monitor-db ~/.local/state/scmm/dev/monitor.sqlite3 \
  --environment dev --monitor-peer-url http://127.0.0.1:5006
```

此命令只新增独立监控数据库及资源配置字段，不覆盖已有监控库或变更认证凭据。路径必须位于仓库和网页可浏览根之外。
开发与生产分别保存监控库；不能共用。监控库保存页面租约摘要、最近访问/实际操作时间以及 24 小时分钟汇总，
不保存会话令牌、密码、请求正文、矩阵或原始任务日志，不纳入项目快照、构建包或 Git。
安全事件仍从独立认证数据库只读查询；自动监控不延长登录时限。监控采样每 5 秒，磁盘容量每 60 秒；
目录/任务探测在限时子进程内执行，慢挂载或探测失败显示待确认。

`monitor_peer_url` 仅允许其他端口的本机 HTTP 地址（127.0.0.1/localhost/::1），不允许路径、查询、凭据、代理转发或重定向。
首次检测旧版生产可不配置令牌，但只会得到“缺少页面登记协议”的无法确认状态；旧版接口的零工作区不再被发布脚本视为空闲。
生产升级到认证/监控版后，在开发资源配置中显式设置 `monitor_peer_token_file`，指向生产初始化生成的仓库外 600 权限运维令牌文件。
运维令牌只能读取 `/api/v1/runtime`，不能查询监控明细或实验数据；令牌缺失/失效不尝试匿名替代。
生产配置使用 `environment: "prod"`，通常不设 peer；生产监控页的“当前实例”即生产本身。

生产首次从旧版迁移须另行协调维护窗口、核实真实用户页面和后台任务，初始化独立认证与监控配置并更新匹配启动器；
不能因旧版无法提供证据而跳过检查。正常发布脚本要求协议 1、15 秒内的采样及明确可更新状态，
同时保留原有连接、任务、工作区检查。维护窗口中的检查与正常在线检测均须在实际发布前执行。


首次从没有认证模块的旧版迁移，在**管理员已协调所有使用者保存、关闭全部生产页面并确认当前维护窗口**后，
先用新版本 `scmm-admin init --environment prod` 初始化独立生产配置和凭据，再执行：

```sh
python3 scripts/scmm_env.py release --migrate-auth
```

该入口只接受尚无认证模块且旧版状态接口明确没有未保存/繁忙工作区的生产版本；
仍检查连接、持久任务、独立 worker、干净 worktree、目标提交和独立资源配置。
页面关闭证据来自已完成的人工协调，脚本不把旧协议的零工作区伪装成页面检测通过。
如果服务已具备新协议、状态不可读、计数异常或仍有活动任务，迁移入口也会拒绝。
脚本在停止生产后安装匹配启动器，备份旧启动器与 unit 到仓库外 `~/.local/state/scmm/pre-auth-launchers-*`；
首次迁移失败时自动恢复旧代码、锁定环境、启动器及 unit，再恢复服务。备份保留供核对；不改动实验数据或撤销新建凭据。
迁移完成后只使用普通 `release`；跨回认证前版本需在维护窗口使用匹配的旧启动器，不能用该入口绕过新协议的未知状态。

## 维护恢复与数据库更新资源

网页 PDF 导出使用锁定的 svglib/ReportLab，附带安全 SVG 检查；无需系统 Cairo。监督维护恢复使用 supervised 可选组中的 skops。

网页 QC/分析 PDF 使用 `web` extra 的 ReportLab（锁定依赖），中文以 STSong-Light CID 字体声明，
不需要服务端浏览器或额外训练模型；已有 Matplotlib Python QC 报告接口继续保留。报告范围与资源边界见[分析说明](statistics.md#统计解释与网页分析)。

管理员在账号页暂存资源配置；维护任务通过用户级 systemd 延后执行并健康检查，失败回滚上一配置，代码更新沿用环境脚本的失败回滚。
批准版本清单位于 `<server-config 所在目录>/<配置名>.recovery/approved.json`（提交 SHA 数组）；只加入已验收或用户明确授权发布的版本。
默认恢复密钥在同目录 key 文件，须连同恢复包和 AI 私有密钥妥善保管，不放入网页可浏览目录或 Git。

LMSD 官方更新来源为 `https://lipidmaps.org/files/?ext=sdf.zip&file=LMSD`，许可 CC BY 4.0。
本批采用 2026-10-19 当前官方包，21,924,109 字节，SHA256 `8ef9664dcde17d7d459819953bac9051db08c7d4f0d88399c53067738a2d02ef`。
源文件 50,586 条，其中有效质量 49,981 条，无效质量 605 条；总组成汇总 21,377 条。
活动指针 `database_provenance.json` 最后发布；版本目录保存 ZIP、`LMSD_metadata.csv.gz`、`LMSD_collapsed_formula_species.csv.gz` 和每个文件的 SHA256。
旧版本保留，不改写旧注释结果绑定的数据库身份。

### Cell PDF 字体

Cell PDF 导出要求服务账号可发现真实且有使用授权的 Arial（常规、粗体、斜体、粗斜体），
通过 Matplotlib 字体发现机制读取并由 ReportLab 嵌入。项目不附带或下载商业字体；
管理员按字体授权安装到服务账号字体目录后，在维护更新时重建该账号的 Matplotlib 字体索引并重启服务。
未找到 Arial 时该规格 PDF 明确报错，通用 PDF 仍可使用原有嵌入字体；SVG 可交给有 Arial 的排版环境处理。
浏览器端 SVG 声明字体、PNG 使用浏览器实际字体，服务器装字体不等于用户浏览器已安装。
具体出版规格见[论文图操作](projects-and-data.md#图表作图数据和报告)。

## 离子后台资源

新离子流程使用独立的本地 worker，旧分析执行方式不迁移。单 API 服务内全局最多一个离子任务，每工作区最多一个。
任务目录位于项目根的 `.ion-jobs/`，冻结 H5AD、参数、任务状态、日志和候选结果不进入正式项目清单。
正式项目保存以完整目录快照为准，临时任务不提供续算或跨工作区接管。

以下为服务器配置键，可用同名大写 `SCMM_` 环境变量覆盖，不属于实验预设：

| 配置键 | 默认值 | 用途 |
|---|---|---|
| ion_task_seconds | 300 | 整任务墙钟上限及 worker CPU 秒数 |
| ion_component_seconds | 30 | 每个竞争组件搜索时间预算 |
| ion_max_states | 100000 | 每组件搜索状态数预算 |
| ion_max_hypotheses | 10000 | 每组件解释数预算 |
| ion_memory_mb | 16384 | worker 虚拟地址空间上限（MiB） |

worker 结果和日志单文件上限 50 MB，网页导入上限 75 MB（含解压科学数组预算），Python 导入可显式选择预算。
Linux worker 绑定父进程死亡信号；取消/维护按进程组限时终止并核实退出。重启把未完成任务标记 interrupted，不能将临时产物冒充正式恢复包。
运行监控包含新任务，部署维护先停止并核实进程退出，再暂存科学工作区。正式模型仍只按已有维护白名单恢复。

## 管理员网页操作

### 管理员监控

管理员从侧栏进入“管理员监控”（`/admin/monitor`）。页面独立于实验工作区，计算繁忙或工作区容量已满时仍可打开；
每 5 秒刷新当前状态，展示主机 CPU/内存/Swap、API 与计算进程资源、存储、最近 24 小时分钟均值/峰值趋势，
以及用户、工作区、持久任务、执行中的请求与安全事件。历史缺口与服务重启显示断线，采样失败保留旧值并标记失效。
CPU 合计以单核 100% 计；RSS 合计可能重复计算共享页。样本进度不等于预计完成时间。
监控只读，账号操作沿用“账号与管理”；不在监控界面取消任务、重启服务、配置路径或删除文件。

“当前实例”和“生产环境”分别检查，开发工作区不能代表生产。生产检查地址和运维凭据仅由管理员在仓库外配置，见
[安装部署](#监控初始化与生产只读检查)。旧版生产缺少页面登记协议时显示“无法确认”。

页面活动包括登录页、前台页面和后台标签页，每个浏览器文档独立登记，正常关闭/刷新时上报关闭。
20 秒心跳只更新页面证据，不自动延长登录会话或工作区寿命；实际键盘/指针操作与后台轮询分开记录。
超过 90 秒未收到心跳、浏览器休眠、崩溃或网络失联的页面标为“关闭待确认”，不能据此认为已关闭。
服务重启后已有登记继续保留，收到新心跳才重新确认；明确关闭的页面记录最多保留 24 小时。
未确认关闭的记录不会自动清除，以避免把失联用户误判为空闲。

只有所有业务页面已关闭、没有打开项目/未保存修改/繁忙工作区/活动任务/未完成业务请求，且采样完整新鲜，才显示“满足更新检查”。
已认证管理员的只读监控页单独计数；其关联工作区仍打开项目或繁忙时照常阻止更新。
检测到旧客户端未登记的业务请求也会显示无法确认；不要用 TCP 连接数为零代替页面关闭证据。
监控保留失联证据，不把超时冒充关闭事实。这里的更新判断是保守空闲诊断；正式发布按[部署优先维护](#发布更新与回滚)限时保全会话，不要求失联页面人工确认。
发布脚本会重新检查，页面上的结果不构成部署授权，也不保证检查之后不会有新页面进入。

### 管理员维护

通常使用“安排维护重启”或填写批准版本后点“安排更新已批准版本”。所有在线用户有 60 秒保存宽限期，
页面暂停新计算，顶部仍可保存项目；随后限时暂存并更新，无需逐人确认或关闭网页。
未保存内容尽力恢复，失联页面/单个会话失败不阻止部署；超时任务会中断，正式写入须安全结束。
更新后页面自动刷新，按登录用户恢复可用工作区并提示恢复结果；未恢复时重新打开正式保存的项目。
详细期限、容量预算和失败处理见[安装部署](#发布更新与回滚)。

“严格会话维护（可选）”保留完整会话恢复要求。该流程中，页面确已关闭但仍有失联记录时，先点“收集全部会话”，再点“读取失联页面范围”。核对本轮失联数量及历史未登记请求，
填写真实的“页面关闭依据”，点击“记录关闭确认并保留工作区”。这是对明确范围的关闭事实登记，不会代替用户保存项目。
已收到用户的同一关闭确认不重复询问；新的活动使审阅失效时重新核对变化范围。5 分钟过期须重新读取范围。
仍在连接的页面不能由这个入口清除，先等待正常关闭回执或完成其草稿收集。随后继续“验证并暂存会话”，通过后才能重启或更新。

账号与管理中可检查并暂存授权原始目录、项目结果、其他输出、缓存、临时及注释数据库目录，重启后加载，不迁移原始文件。
官方数据库更新保留旧 SDF、原始 ZIP、完整元数据、总组成候选汇总及校验来源记录。
可选严格维护按“收集全部会话 → 验证并暂存会话 → 重启/更新已批准版本”执行；收集期间禁止新增科学修改，
等待任务完成并要求每个页面确认草稿，失联/旧协议/快照或恢复校验失败会阻止执行。管理员可以取消维护。
恢复包括用户隔离的未保存矩阵、起点、结果、参数草稿、页面、图与选择、聊天和受审核的已训练模型。
更新入口只允许批准清单中的远端版本；重启失败恢复上一配置并进行健康检查。

### 存储清理与自动保留

管理员另可展开“持续自动保留（默认关闭）”，沿用上方年龄/数量草稿并显式填写检查间隔（分钟），
点击“审阅自动保留规则”后阅读授权范围，再点击“启用持续自动保留”。此授权适用于该项目未来符合规则的产物，
与一次性冻结清单不同；即使当前没有清理候选也可启用。草稿修改会清除旧审阅，已生效规则单独显示。
首轮在所设间隔后检查，服务重启后保留策略；项目打开/繁忙时跳过，关闭后等下一轮，
引用/任务状态无法核实或执行失败时停用，检查回收区与运行记录、处理问题后重新审阅启用。
“刷新自动保留状态”读取生效规则、下次检查及最近 50 轮记录；“停用自动保留”阻止后续轮次，
当前文件复制会在安全检查点停止，已移走内容尝试恢复，已完成归档仍保留。不是立即中断 I/O。
持续规则仅自动移入回收区，仍需管理员单独永久清空才释放磁盘，不自动保存项目或清空回收区。
恢复旧产物不会停用规则；若恢复后需要持续保留，应先由管理员停用或调整规则，否则仍可能在后续周期再次符合清理条件。
项目整体与独立结果继续使用原有删除计划。

| 参数 | 默认 | 类型与含义 |
|---|---|---|
| `min_age_days` | 空 | 非负整数天，空值不按年龄筛选；按产物内最新修改时间计算 |
| `keep_latest` | 空 | 每类至少保留的最新数量，非负整数；边界同时间项全部保留 |
| `interval_minutes` | 无表单默认值，须显式填写 | 1–525600 的整数分钟；首轮在该间隔后检查，随后按生效规则定期重查 |

年龄/数量同时填写时共同限制清理，两项都空不能启用持续规则；零值可取消对应限制，但不能绕过引用/活动/未知状态保护。
前两项也用于只读建议和一次性清单。持续规则另须管理员审阅启用，作用于未来产物，

服务默认在当前项目根 `.scmm-retention.sqlite3`（SQLite `user_version=1`）持久化每项目策略、生效修订、启用管理员 ID、
下次检查时间，以及最近 50 轮的开始/结束/状态/错误与归档条目索引；不写入 `project.json`、H5AD 或维护工作区快照。
这是环境级管理状态，不属于项目主动保存。可按[部署配置](#访问与路径配置)明确指定独立本地 `retention_db`，支持项目目录位于不兼容 SQLite 文件锁的共享盘；既有数据库须停服备份迁移，不自动切换。
开发/生产数据库分别隔离；移动项目不自动迁移或重绑定策略。
备份应保留该数据库；还原后仍需核对项目身份与未完成归档。未知数据库版本/结构拒绝使用，不自动降级、覆盖或切换路径。

单 API 进程仅有一个自动保留执行线程，逐项目串行检查，约每 5 秒检查到期规则。
首轮在显式间隔后运行，错过周期合并为一轮，不创建追赶任务或无限并发；检查时间不是 ETA。
各轮沿用同一引用/活动保护、短管理锁预留、存储锁和完整归档/恢复协议，不计算或修改科学矩阵。
打开/正在打开/正清理的项目本轮跳过，保持策略，下一周期重查；状态未知或清理失败时停用策略。
失败/中断不会自动重放，已有 `prepared/restoring` 归档须先恢复，才能重新审阅启用。
停用后当前文件复制等待安全检查点，取消剩余复制/移走，必要时恢复已移走成员；不谎报立即取消 I/O。
正常重启保留启用规则和下次检查；旧进程的 `running` 记录标为 `interrupted` 并停用关联策略，
不得把服务重启当成未知写操作的重试。状态持久化失败或执行线程异常停止时监控保留未知证据。
有效后台运行进入管理员任务和更新门禁；维护快照检查与后台任务准入在同一管理锁下互斥，冻结后不再启动新轮次。
持续策略只移入回收区，不永久清空；回收区仍占磁盘，不以自动保留冒充空间已释放。

## 监控与项目快照的边界

监控 SQLite 独立保存最近 24 小时资源分钟汇总、页面登记摘要和账号最近访问/实际操作时间；
与认证 SQLite 分开，位于仓库和网页浏览根之外。两者都不属于实验项目，不进入项目快照、H5AD 或导出包。
监控只读取项目和任务的少量状态元数据，不读写实验矩阵；打开项目的来源仍由原项目清单和工作区管理。
页面失联记录不会随 24 小时曲线自动清除；维护及保守更新判断见[管理员监控](#管理员监控)。

## 服务维护恢复包

维护包与主动保存项目不同，位于资源配置旁的 `<配置名>.recovery/`，不随项目/缓存/临时根切换。
目录权限 0700、文件 0600；状态和校验清单用独立密钥加密认证，先完整写入并验证恢复，再原子发布 current 指针。
包含各用户工作区的当前 AnnData、完整起点、报告、视图、草稿与页面状态；原始文件只保留身份引用和视图数据，不复制原始谱。
切换项目根后，维护包中已验证的既有项目继续在原目录保存，新项目写入新根；不自动迁移项目。
原始目录授权被移除或输入身份改变时，保留分析状态及只读图，关闭旧原始读取句柄并提示重新定位。
聊天仍在按用户隔离的独立加密 AI 数据库中，不进入共享项目或明文恢复元数据。
训练模型使用 skops 显式类型白名单、版本和自定义实现指纹，仅允许本服务创建的包；验证留出预测逐值一致后才发布和恢复。
依赖/实现改变或文件校验失败会拒绝对应会话，不执行任意 pickle 导入，不以重训代替恢复。
部署优先维护为每个可用工作区建立独立验证包，以加密认证的 current 清单关联；暂存/恢复均限时且有容量预算。
单个失败、超限或超时的临时会话不阻止更新和其他用户恢复，损失范围留在私有维护报告；旧指针隔离，失败包不自动重试。
正式项目内容不随临时会话失败回滚或删除。具体期限与限制见[安装部署](#发布更新与回滚)。
正式项目快照仍只保存可执行模型之外的数据和只读报告；重开正式项目需重新训练才能继续模型计算。

## 部署与运维排错

### `ModuleNotFoundError: pyopenms` 或科学计算包缺失

确认当前解释器属于项目环境：

```bash
uv sync --locked --all-extras --dev
uv run --locked python -c "import sys; print(sys.executable)"
uv run --locked python -c "import pyopenms, numpy, pandas, anndata"
```

解释器应位于仓库的 `.venv`；正式使用通过服务器网页。

### 网页任务与服务

- **打开项目报 `'ascii' codec can't decode`**：中文全局预设按 UTF-8 保存，但旧代码可能随进程默认编码读取。
  本机 PyOpenMS 导入会将原生 locale 切换为 `C`，即使 `LANG` 原先是 UTF-8 也可能出现。
  修复使用显式 UTF-8 读取预设/缓存；旧服务可启用 `PYTHONUTF8=1` 后重启，
  先保存并关闭页面并检查活动任务，见[服务安装](#开发与生产分离)。无需重建项目或转换 H5AD。
- **提取完成但无法分析**：在「提取」选择成功样本，确认纳入并建立当前数据。
- **操作长时间等待**：细胞预览在独立进程执行，检查预览按钮下方阶段提示；失败后可重新运行。
  打开原始文件、分析与保存仍同步，单扫描自动在会话后台读取；不要重复提交。后台批次状态不是这些操作的进度或 ETA。
- **反代访问时操作卡住或请求超时**：在浏览器网络面板检查 `/api/v1/` 请求、状态码，以及代理和服务日志。
  当前 Vue 使用 HTTP 请求与轮询，检查代理是否同时转发页面和 API；长计算需核对实际生效的请求超时。
  细胞预览在独立进程计算并轮询状态，原始打开、分析和保存需等待请求完成。
  延长代理超时不能修复后端阻塞；网页与直连都无响应时检查服务 CPU、内存及处理阶段。
- **停止后仍在运行**：停止仅阻止后续样本，当前读取/计算需完成。
- **刷新后结果消失**：未保存会话不会自动恢复；主动保存项目后再离开，未应用表单不属于已保存参数。
- **Worker no longer running**：提供完整批次 ID 和下载的 worker 日志。中文 JSON 在无 locale 的 systemd 环境
  曾触发 ASCII 解码错误，现已统一 UTF-8 并写回启动失败状态；不能把所有退出都归为旧问题。
- **更新后界面没变或 origin 403**：核对服务工作目录、启动时间、构建资源与请求的 Origin/Host；
  浏览器页面和 API 必须同源，反代需保留正确的请求主机名，见[服务部署](#发布更新与回滚)。
- **Thermo reader / .NET 缺失或 centroid 报错**：检查[RAW 依赖与范围](#thermo-raw-额外依赖)，失败不自动转换。

### 登录或资源配置失败

- 普通 HTTP 地址打开后白屏、控制台提示 `crypto.randomUUID is not a function`：属于旧前端在非安全上下文调用受限浏览器接口；更新到修正版并刷新页面。页面登记改用普通 HTTP 可用的 `crypto.getRandomValues`，保留随机性；不需要为排错临时关闭浏览器安全检查。
- 启动提示配置/认证数据库缺失：管理员先检查仓库外资源文件及优先级；首次部署执行初始化，已有部署不要重新初始化覆盖账号。缺认证不会匿名启动。
- 启动在 `RetentionScheduler` 报 `database is locked`：先检查是否确有其他进程占用；若项目目录在 CIFS 共享盘，确认挂载支持 SQLite 文件锁。可在停服后备份并迁移策略数据库，通过[资源配置](#访问与路径配置)将 `retention_db` 指向独立本地持久路径；已有规则不得用空库替换，不通过关闭锁或改为内存库绕过。
- 一次性凭据失效：凭据限首次登录且 24 小时内有效；已消耗、超时或首次设密中断时由管理员重置，命令见[账号初始化与恢复](#服务器初始化与账号)。
- 内部 HTTP 登录后仍返回 401：检查该开发配置是否显式关闭 Cookie Secure 标记、开发与生产是否使用不同 Cookie 名；Cookie 不按端口隔离。
- 修改接口返回 403：区分管理员权限、请求来源和 CSRF 错误，重新登录获取有效会话；不自动重放保存或计算请求。
- 注释/RAW 路径失效：由管理员核对对应可选资源配置和文件，不在网页修改服务器路径。已保存注释仍可查看，运行新注释需要可用数据库。


### 监控显示无法确认或暂不可更新

- 首次采样/CPU 未建立增量：稍等下一次 5 秒采样；曲线缺口保留，不将缺测解释为零。
- “监控数据库未配置/初始化”：已有认证配置执行[监控初始化](#监控初始化与生产只读检查)，核对独立文件及 600 权限；普通启动不会自动创建替代库。
- 页面“关闭待确认”：后台标签页、浏览器休眠、崩溃或断网不会自动等同关闭。协调对应用户恢复连接并正常关闭，不能通过清除浏览器 Cookie 代替服务器关闭证据。
- 有打开项目或未保存修改：对应用户回到工作区保存、关闭项目，再关闭业务页面。繁忙或不可读工作区保持阻塞/待确认，监控不等待计算锁或代替用户保存。
- 旧客户端未登记：需要核对原页面及会话，协调维护窗口；不按 TCP 为零、长时间无请求或人工猜测判定空闲。
- 生产仍为旧版：旧接口没有页面登记协议，只能返回无法确认；首次认证/监控迁移按安装说明协调维护窗口。开发状态不能作为生产关闭证据。
- 生产检查无法读取：核对本机目标端口、`environment: "prod"`、配置的运维令牌文件权限和服务状态；配置了令牌而读取失败时不尝试匿名。
- 历史任务显示运行但进程不存在：任务状态文件可能在异常退出时未更新，仍需核对任务产物与进程，不在监控页擅自改写任务或删除目录。
- 自动保留跳过：先确认项目已在所有工作区关闭，正在打开或被清理/恢复的项目本轮跳过，下一间隔重查。
  规则失败后停用或服务中断后标为 `interrupted`：查看最近运行记录与共享回收区，先恢复 `prepared/restoring` 条目，
  处理路径冲突、空间或引用异常，再由有效管理员重新审阅启用；不直接修改 SQLite 或删除恢复副本来绕过门禁。
  停用等待安全检查点，不是立即终止文件 I/O；回收区仍占磁盘，永久清空是独立操作。
