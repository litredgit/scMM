<script setup lang="ts">
import { useWorkspace } from '../stores/workspace'
const store = useWorkspace()
const operations = [
  [
    '新建项目',
    '立即创建项目目录、project.json 和 processing / snapshots / exports / analyses 子目录；此时不一定有矩阵。',
  ],
  ['编辑样本 / 应用参数', '先更新工作区；保存项目后更新 project.json。未应用表单仍是草稿。'],
  ['查看原始谱', '读取原始文件并生成工作区图表，不建立当前矩阵；原始谱只引用，不复制。'],
  [
    '预览细胞窗口',
    '写 processing/preview-jobs/<ID>/request.json、state.json；缓存位于 processing/preview-<ID>/，含 data.h5ad、targets.npy、traces.csv、detection.json、identity.json；共同特征缓存为 shared-<摘要>.npy / .json。尚未审核纳入。',
  ],
  [
    '开始提取 / 重试',
    '先完整保存项目（已有矩阵时也生成新快照），再写 processing/<批次>/request.json、state.json、worker.log、逐样本 H5AD、共同特征数组和检测曲线。',
  ],
  [
    '审核建立数据 / 预处理 / 分析',
    '更新当前工作数据，尚未发布新项目快照。提取文件已落盘不代表当前分析已保存。',
  ],
  [
    '保存项目',
    '先写 snapshots/<时间_修订号_ID>/：当前矩阵 H5AD、baseline.h5ad、views.json；完整写好后更新 project.json。无矩阵时只保存配置及已有视图。',
  ],
  [
    '服务器独立导出 H5AD',
    '默认写项目 exports/，也可选择配置允许的位置；不覆盖已有文件，不更新项目快照，不含完整预处理起点。',
  ],
  [
    '下载图片 / 表格 / 报告',
    '下载到浏览器所在电脑，不在项目中自动留副本，不保存项目。“上次保存 H5AD”只读取上次快照。',
  ],
  ['移入回收站', '移动到共享回收区，仍占磁盘；恢复不覆盖已有内容，管理员永久清空后才释放空间。'],
]
</script>
<template>
  <details class="save-explanation">
    <summary>什么操作会写入哪些文件？</summary>
    <p>
      项目位置：{{
        store.project?.path ?? store.configuration?.project_root
      }}。文件名时间为北京时间，清单时间戳为 UTC。
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>操作</th>
            <th>保存位置与边界</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[operation, detail] in operations" :key="operation">
            <td>{{ operation }}</td>
            <td>{{ detail }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted">
      项目快照保留当前矩阵、完整预处理起点与只读图表 /
      报告，不保存可执行训练模型；历史快照会累积，不提供历史项目分支切换。维护恢复与项目保存分别管理。
    </p>
  </details>
</template>
