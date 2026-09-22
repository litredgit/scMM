# 外部源码快照的本地版本管理

外部作者不使用 Git。每次复制来的文件夹作为一次完整交付保存，Git 提交记录
接收顺序，不代表作者实际的开发历史。快照与本项目的功能移植提交分别管理。

## 布局

- `.upstream-snapshots.git/`：独立的本地裸仓库，`snapshots` 分支串联所有交付。
- 裸仓库的 `snapshot/<名称>` 标签：定位每次交付，重复导入不会创建重复提交，
  同名但内容不同则拒绝导入，需指定新名称。
- 主仓库的 `vendor/snapshots` 分支：同步快照提交及对象，方便与 `develop` 比较。
  日常继续在 `develop` 工作；不要直接向快照分支提交自己的改动。
- 原始文件夹保留原位，通过主仓库 `.git/info/exclude` 本地排除；导入后在原文件夹
  手工修改的内容不会自动进入快照，需再次显式导入并使用新名称。

只有包源码的交付统一映射到 `scMM/`；完整项目保持原有布局，因此相同模块在
不同交付间可以直接比较。保留源码、配置、安装脚本、PDF 和其他交付文件的字节内容
及可执行位；跳过 Git 内部目录、Python 字节码和常见环境/测试缓存，不读取软链接目标。
主项目的文件忽略规则不会导致上游图片或 PDF 漏收。
项目打包范围限定为正式的 `scMM` 包及其子包，避免其他同名前缀的交付目录进入安装包。

每次提交的 `.snapshot.json` 记录原文件夹名、布局、接收日期、导入时间、
排除项、文件大小、可执行位和 SHA-256。用户提供的历史基点只记录为来源信息，
不会伪造共同祖先。新增交付里不存在的文件在新版本中移除，旧版本仍可从标签取回。

## 首次收录

| 原始目录 | 接收日期 | 文件数 | 提交 | 标签（独立仓库） |
|---|---|---|---|---|
| `scMM-new/` | 2026-09-21 | 21 | `bdce317` | `snapshot/scMM-new` |
| `SCMM-GUI-0.2.0-source/` | 2026-09-22 | 39 | `f961809` | `snapshot/SCMM-GUI-0.2.0-source` |

文件数不包含导入工具生成的 `.snapshot.json`，也不包括忽略的 Python 缓存。

第一份交付的用户声明基点：`e0357ac3833e0fa5a00e93944ff0a9ef9d5f6485`。
第二份交付没有声明 Git 基点，不做推断。

## 后续导入

把新交付复制到项目根目录，然后运行（命令均从项目根目录执行）：

```sh
.venv/bin/python scripts/import_upstream_snapshot.py 新复制的文件夹
```

同一目录被重新使用时，为更新后的内容指定新名称：

```sh
.venv/bin/python scripts/import_upstream_snapshot.py 新复制的文件夹 --name 新版本名称
```

可选 `--received-date YYYY-MM-DD` 记录实际接收日期。脚本不会执行交付源码、
安装其依赖、切换当前分支或改动当前暂存区。需要写入本地 Git 对象、引用和
`.git/info/exclude`；在把 `.git` 设为只读的沙箱中需要相应的 Git 写入权限。

## 查看与比较

```sh
# 主仓库：接收历史、最近两份交付差异、与我们维护版本的代码差异。
git log --oneline vendor/snapshots
git diff --stat vendor/snapshots~1 vendor/snapshots
git diff develop vendor/snapshots -- scMM/

# 独立仓库：标签、任意两次交付的差异、来源记录。
git --git-dir=.upstream-snapshots.git tag --list 'snapshot/*'
git --git-dir=.upstream-snapshots.git diff snapshot/scMM-new snapshot/SCMM-GUI-0.2.0-source -- scMM/
git --git-dir=.upstream-snapshots.git show snapshots:.snapshot.json
```

这些命令不切换工作区。由于上游快照历史独立，不应将整个快照分支直接合并到
`develop`；继续按功能审阅、移植并单独测试和提交。

## 备份

两个仓库都在本机，不会自动推送到远端。主仓库包含快照提交对象，但标签保存在
独立仓库；普通推送 develop 不会发布这些快照。可用 bundle 备份完整快照历史和标签，
输出请使用尚未存在的新文件名，并另存到其他磁盘：

```sh
git --git-dir=.upstream-snapshots.git bundle create /tmp/scmm-upstream-备份日期.bundle --all
```

从备份恢复独立仓库时，使用一个新的目录：

```sh
git clone --bare /tmp/scmm-upstream-备份日期.bundle /tmp/scmm-upstream-restored.git
```

## 本次验证

2026-09-22：两份交付共 60 个文件逐一与 Git 对象比较，字节内容完全一致，
裸仓库 `git fsck --full` 通过。自动化测试覆盖路径归一化、PDF 保留、文件删除历史、
重复导入、同名冲突、软链接拒绝，以及主分支和暂存区保持不变。
全项目 `pytest -q -W error` 共 188 项通过，格式、静态检查及依赖锁校验通过。
