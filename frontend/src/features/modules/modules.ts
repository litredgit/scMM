export type ModuleKey = 'extraction' | 'annotation' | 'statistics'

export const modules = [
  {
    key: 'extraction' as ModuleKey,
    path: '/cell-extraction',
    name: '细胞提取',
    subtitle: '从原始谱建立细胞 × 特征矩阵',
    description: '检查原始谱、设置提取参数，并人工审核纳入细胞。已有提取数据也可以独立导入。',
    input: 'mzML · mzXML · profile RAW · scMM 交换包',
    output: '审核后的矩阵 · 细胞与特征信息 · 提取记录',
    steps: [
      { path: '/cell-extraction', name: '选择数据来源' },
      { path: '/samples', name: '添加原始文件' },
      { path: '/raw', name: '预览' },
      { path: '/extraction', name: '提取' },
    ],
  },
  {
    key: 'annotation' as ModuleKey,
    path: '/annotation',
    name: '特征注释',
    subtitle: '在谱图中连接峰、候选与人工证据',
    description: '导入特征表或矩阵，选择数据库，查看同位素与加合关系，保留多候选和人工审核。',
    input: 'm/z 特征表 · 定量矩阵 · scMM 交换包',
    output: '候选与证据 · 峰关系 · 审核记录 · 注释数据',
    steps: [
      { path: '/annotation', name: '候选与关系审核' },
      { path: '/annotation/evidence', name: '证据与导入' },
      { path: '/ions', name: '定量视图' },
    ],
  },
  {
    key: 'statistics' as ModuleKey,
    path: '/statistics',
    name: '统计分析',
    subtitle: '从定量矩阵到可追溯的统计结果',
    description: '直接使用提取矩阵或导入外部矩阵，检查数据、预处理、探索和比较。注释是可选信息。',
    input: '细胞或样本矩阵 · 元数据 · H5AD · scMM 交换包',
    output: '完整处理矩阵 · 统计结果 · 图表与报告',
    steps: [
      { path: '/statistics', name: '选择数据来源' },
      { path: '/data-check', name: '数据检查' },
      { path: '/data-editor', name: '数据编辑' },
      { path: '/preprocess', name: '预处理' },
      { path: '/analysis', name: '分析' },
    ],
  },
]

export function moduleForPath(path: string) {
  return modules.find((module) => module.steps.some((step) => step.path.split('?')[0] === path))
}
