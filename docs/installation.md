# 安装与部署

[返回文档索引](README.md)

本页负责环境安装、启动配置与服务更新；网页操作见 [工作流程](workflow.md)，
参数含义见 [参数参考](parameters.md)，reader 构建与协议见 [RAW 技术说明](thermo-raw.md)。

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
[Thermo RAW 技术说明](thermo-raw.md)。不会在直接读取失败时自动转换 mzML；
旧 `--msconvert` / `msconvert_path` 参数及手动转换模块已移除。

## 使用 Notebook

完整同步已经包含 `notebook` extra。启动项目内的 JupyterLab：

```bash
uv run --locked python -m ipykernel install --user --name scmm --display-name scMM
uv run --locked jupyter lab
```

打开项目根目录的 `scMM_workflow.ipynb`，选择显示名为 `scMM`、内部名称为 `scmm` 的内核。
VS Code 也可直接选择仓库内的 `.venv/bin/python`。Notebook 的功能和参数见
[参数化 Notebook 工作流](workflow.md)。

## 依赖分组

| 分组 | 主要用途 |
|---|---|
| 核心依赖 | 原始谱读取、矩阵处理、保存、归一化、基础统计 |
| `plot` | Matplotlib/Seaborn、UMAP、Palantir 和轨迹图 |
| `cluster` | Leiden 与 Louvain 聚类 |
| `supervised` | 监督学习、SMOTE 和 SHAP |
| `web` | FastAPI/Uvicorn、Plotly、Matplotlib、NetworkX、UMAP 及兼容依赖；Vue 构建工具由 npm 单独管理 |
| `notebook` | JupyterLab 与项目内核 |
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
`--config` / `SCMM_UI_CONFIG` 仍仅管理实验参数，格式见[参数参考](parameters.md#网页默认参数)。

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

用户在[我的账号](workflow.md#ai-分析助手)保存地址、模型和新 Key；配置按登录用户隔离，
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
项目根、缓存、预设和临时目录仍分别隔离；这些是部署目录约定，实际资源值由仓库外配置指定。回收及清空操作见[网页指南](workflow.md#保存和离开)。
自动保留策略与最近运行记录默认保存在各环境项目根的 `.scmm-retention.sqlite3`，可用 `retention_db` 明确指定仓库外、不可浏览的本地持久路径；父目录须已存在。
CIFS 等共享盘可能不支持 SQLite 文件锁，项目仍可留在共享盘，数据库须选择支持 SQLite 的本地磁盘，并按开发/生产隔离。指定路径失败时报错，不自动切换或创建父目录。
已有策略迁移须在服务停止后备份并完整复制数据库，不能用空库代替；备份包含所配置路径。策略按项目 ID 和启用管理员授权隔离，
默认无启用规则；备份项目根时保留此环境管理数据库，不把它当缓存清理。服务保持单进程、一个串行自动保留线程。
正常停止会等当前归档到达安全检查点，维护暂存/更新检查会阻止跨越正在运行或无法核实的清理。
异常退出的运行不会自动重放，检查回收区并处理后重新审阅启用；详情见[持续自动保留](data-output.md#持续自动保留)。

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
[公网完成记录](roadmap.md#公网完成状态与历史后续)；实际访问范围以服务器配置为准。
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
[网页参数](parameters.md#网页注释与同位素)与[工作流程](workflow.md#注释与同位素)。

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
历史合成项目与浏览器证据保留原目录，见 [CHANGELOG 检验记录](../CHANGELOG.md#历史独立环境与检验步骤)；
若需要在 5007 复用，须显式导入或复制到开发根，不把真实生产项目作为调试写入目标。

## 发布、更新与回滚

任务完成并通过相关检查后，更新 5007 开发服务供用户验收，保留修改且不自动提交。
用户明确确认本任务或里程碑验收通过后，再提交、推送并部署生产；协作授权约定见
[代理工作指南](../AGENTS.md#协作约定)。

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
发布前执行 [开发验证](development.md#完整验证)。脚本串行锁定环境操作，检查生产浏览器连接、
未结束任务和 worker；Vue 另检查 `/api/v1/runtime` 的未保存及繁忙工作区，状态无法读取时拒绝更新。
满足空闲条件，或全部会话已完成维护暂存、验证并冻结后，停止服务再变更代码及依赖。新进程通过 systemd 状态和首页 HTTP 检查后，
`release` 才推送远端 `main`；网络推送失败时，本地新服务已生效，修复网络后补推即可。
依赖同步或健康检查失败时，脚本尝试恢复原提交、锁定依赖和服务；若恢复本身失败，按错误和日志处置，
原提交仍保存在 `refs/scmm/recovery`。脚本不会替用户完成科学验收，也不替代发布前测试。

回滚将本地 `main` 指针恢复到指定版本，并在 `refs/scmm/previous` 保存切换前版本；
不强推远端，不删除或恢复项目结果。再次 `rollback` 可切回刚才的版本，
`update prod` 会重新部署远端 `main`。回滚后的新版本发布仍须包含远端 main 的历史，避免非快进推送；
永久撤销应在 `dev` 中提交修复后正常发布。保存格式若已变化，须另外评估旧代码读取新项目的兼容性。

已授权发布优先通过维护暂存/恢复处理未保存会话：发起维护收集、收齐页面草稿，
完成全部工作区暂存及恢复验证后冻结，再运行标准发布；无活动页面的未保存工作区直接暂存。
新进程启动后核对恢复数量、工作区身份及未保存状态，维护暂存不代替用户主动保存。
失联页面缺失草稿、运行中任务或暂存/验证失败仍须先处理，不得直接重启丢弃状态；
关闭页面也不表示服务端工作区已经保存。
若已核实相关页面全部关闭但关闭回执丢失，管理员在账号页先收集会话，再读取失联页面范围、填写关闭依据并执行关闭确认。
审阅绑定当前服务实例、维护轮次、失联记录和未登记请求代次，5 分钟内有效；新页面、目标心跳、新未登记请求或执行中的业务请求都会拒绝旧确认。
确认仅关闭审阅中的失联租约并解除对应历史未知请求，既有连接页面、任务、工作区和未保存状态保留；随后仍须执行并通过完整维护暂存/恢复验证。
管理员自己的维护页面继续正常收集草稿，不会被当作失联页面清除。只读运维令牌仍仅允许查询 runtime，不因此获得维护写权限。
不支持该入口的旧进程不会通过修改代码文件自动获得能力；此时应准确报告旧版维护能力缺口，不能反复把用户已给出的关闭确认当作缺失，也不能伪造空闲证据强行发布。
HTTP 200 不能代替六步流程或真实实验验收。可查看服务及具体运行目录：

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
不需要服务端浏览器或额外训练模型；已有 Matplotlib Python QC 报告接口继续保留。报告范围与资源边界见[分析说明](analysis.md#统计解释与网页分析)。

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
具体出版规格见[论文图操作](workflow.md#论文图细胞联动与热图)。
