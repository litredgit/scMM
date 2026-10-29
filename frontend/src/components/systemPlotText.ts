import type { Figure } from '../api/types'

// Compatibility for system labels in saved figures. Data arrays, category names,
// user result keys and custom export text are deliberately never translated.
const labels: Record<string, string> = {
  强度: 'Intensity',
  总强度: 'Total intensity',
  检出特征数: 'Detected features',
  净强度: 'Net intensity',
  平均强度: 'Mean intensity',
  归一化强度: 'Normalized intensity',
  'RT（秒）': 'RT (s)',
  '时间（秒）': 'Time (s)',
  特征: 'Feature',
  细胞: 'Cell',
  分组: 'Group',
  行标准分: 'Row z-score',
  窗口强度: 'Window intensity',
  伪时间: 'Pseudotime',
  '平均绝对 SHAP': 'Mean absolute SHAP',
  特征值: 'Feature value',
  预测类别: 'Predicted class',
  真实类别: 'True class',
  召回率: 'Recall',
  精确率: 'Precision',
  '假阳性率（FPR）': 'False positive rate (FPR)',
  '真阳性率（TPR）': 'True positive rate (TPR)',
  预测概率: 'Predicted probability',
  实际阳性比例: 'Observed positive fraction',
  常数轴: 'Constant axis',
  窗口编号: 'Window index',
  参考强度: 'Reference intensity',
  细胞数: 'Cell count',
  来源: 'Source',
  标准化趋势: 'Standardized trend',
  '窗口（时间递增排序）': 'Window (increasing time)',
  'RT（秒；计算按扫描顺序）': 'RT (s; computed in scan order)',
  '总离子流 TIC': 'Total ion chromatogram (TIC)',
  '提取离子流 EIC': 'Extracted ion chromatogram (EIC)',
  合并谱: 'Summed spectrum',
  单扫描谱: 'Single-scan spectrum',
  细胞窗口与参考峰顶: 'Cell windows and reference apices',
  参考信号与细胞窗口: 'Reference signals and cell windows',
  净信号与判定门槛: 'Net signals and thresholds',
  细胞质谱对比: 'Cell mass spectra',
  '每细胞 QC · 当前矩阵': 'Cell quality control · current matrix',
  '每细胞 QC · 未应用预览': 'Cell quality control · unapplied preview',
  特征热图: 'Feature heatmap',
  双特征散点: 'Feature scatter',
  特征距离嵌入: 'Feature distance embedding',
  留出测试集混淆矩阵: 'Held-out confusion matrix',
  '留出测试集 ROC': 'Held-out ROC',
  '留出测试集精确率–召回率': 'Held-out precision-recall',
  '留出测试集校准诊断（不重新拟合）': 'Held-out calibration (without refitting)',
  '火山图：全部特征的全局 BH-FDR': 'Volcano plot: global BH-FDR across all features',
  '特征相关网络（不代表因果或轨迹）': 'Feature correlation network (not causality or trajectory)',
  '小提琴图（零值仅从显示中隐藏；检验与全局 FDR 不变）':
    'Violin plot (zeros hidden for display; tests and global FDR unchanged)',
  '小提琴图（包含零值；使用同一份全局 FDR）': 'Violin plot (zeros included; same global FDR)',
  '原始信号、基线与重构': 'Raw signals, baselines and reconstruction',
  扣基线信号与秩一近似: 'Baseline-corrected signals and rank-one approximation',
  峰重构残差与逐通道噪声: 'Peak reconstruction residuals and channel noise',
  独立原始信号诊断: 'Independent raw signal diagnostics',
  '采集稳定性 QC': 'Acquisition stability QC',
  参考特征强度分布: 'Reference feature intensity distributions',
  各窗口细胞数: 'Cell counts per window',
  来源中位强度谱相关: 'Correlation of source median spectra',
}
function text(value: unknown) {
  if (typeof value !== 'string') return value
  return labels[value] ?? value.replace(/^维度 (\d+)$/, 'Dimension $1')
}
function title(holder: Record<string, unknown>) {
  if (typeof holder.title === 'string') holder.title = text(holder.title)
  else if (holder.title && typeof holder.title === 'object') {
    const value = holder.title as Record<string, unknown>
    value.text = text(value.text)
  }
}
export function systemPlotText(figure: Figure, key: string) {
  const meta = (figure.layout.meta ?? {}) as Record<string, unknown>
  if (meta.system_text_language === 'en') return figure
  const userTitle = !!meta.embedding || key.includes('embedding_plot') || key === 'embedding'
  if (!userTitle) title(figure.layout)
  const plotTitle = figure.layout.title as { text?: string } | undefined
  if (plotTitle?.text && meta.time_result_key)
    plotTitle.text = plotTitle.text
      .replace(/^窗口代谢速度 · /, 'Window metabolic velocity · ')
      .replace(/^滑动窗口轨迹 · /, 'Sliding-window trajectory · ')
      .replace(/^代谢趋势 · /, 'Metabolic trends · ')
      .replace(/^趋势聚类 · /, 'Trend clusters · ')
  const userAxes = key.includes('feature_scatter')
  for (const [name, value] of Object.entries(figure.layout)) {
    if (/^[xy]axis\d*$/.test(name) && value && typeof value === 'object' && !userAxes)
      title(value as Record<string, unknown>)
    if (/^scene\d*$/.test(name) && value && typeof value === 'object')
      for (const axis of Object.values(value))
        if (axis && typeof axis === 'object') title(axis as Record<string, unknown>)
  }
  for (const annotation of (figure.layout.annotations ?? []) as Record<string, unknown>[])
    if (!userTitle) {
      annotation.text = text(annotation.text)
      if (meta.trend_cluster_parent && typeof annotation.text === 'string')
        annotation.text = annotation.text.replace(
          /^簇 (\d+) · (\d+) 个特征$/,
          'Cluster $1 · $2 features',
        )
    }
  // Only the raw cell detection graph has these generated trace names.
  const rawCells =
    key === 'raw.cell_pane' ||
    key === 'extraction-signal' ||
    key.startsWith('batch-comparison-signal')
  for (const trace of figure.data as Record<string, unknown>[]) {
    if (key.includes('calibration') && trace.name === '理想校准') trace.name = 'Ideal calibration'
    if (key.includes('network')) {
      if (trace.name === '正相关') trace.name = 'Positive correlation'
      if (trace.name === '负相关') trace.name = 'Negative correlation'
      if (trace.name === '特征') trace.name = 'Features'
    }
    if (meta.time_result_key && typeof trace.name === 'string') {
      if (plotTitle?.text?.startsWith('Palantir')) {
        if (trace.name === '细胞') trace.name = 'Cells'
        if (trace.name === '所选根点') trace.name = 'Selected root'
      }
      if (plotTitle?.text?.startsWith('Window metabolic velocity') && trace.name === '速度范数')
        trace.name = 'Velocity norm'
      if (meta.trend_cluster_parent && typeof trace.name === 'string')
        trace.name = trace.name.replace(/^簇 (\d+) 均值$/, 'Cluster $1 mean')
    }
    if (trace.type === 'waterfall' && Array.isArray(trace.x)) {
      if (trace.x[0] === '基准') trace.x[0] = 'Baseline'
      if (trace.x.at(-2) === '其他特征') trace.x[trace.x.length - 2] = 'Other features'
      if (trace.x.at(-1) === '预测输出') trace.x[trace.x.length - 1] = 'Prediction'
    }
    if (rawCells && typeof trace.name === 'string')
      trace.name = trace.name
        .replace(/^峰顶 /, 'Apex ')
        .replace(/^净信号 /, 'Net signal ')
        .replace(/^门槛 /, 'Threshold ')
    if (rawCells && Array.isArray(trace.text))
      trace.text = trace.text.map((value) =>
        typeof value === 'string' ? value.replace(/^细胞 (\d+)$/, 'Cell $1') : value,
      )
    if (typeof trace.hovertemplate === 'string') {
      const templates: Record<string, string> = {
        '细胞=%{customdata[0]}<br>强度=%{y:.1e}<extra>%{fullData.name}</extra>':
          'Cell=%{customdata[0]}<br>Intensity=%{y:.1e}<extra>%{fullData.name}</extra>',
        'm/z=%{x:.5f}<br>强度=%{y:.1e}<extra>%{fullData.name}</extra>':
          'm/z=%{x:.5f}<br>Intensity=%{y:.1e}<extra>%{fullData.name}</extra>',
        '细胞 %{hovertext}<br>x=%{x}<br>y=%{y}<br>强度 %{marker.color:.1e}<extra></extra>':
          'Cell %{hovertext}<br>x=%{x}<br>y=%{y}<br>Intensity %{marker.color:.1e}<extra></extra>',
        '文件：%{customdata[1]}<br>当前总强度：%{x:.1e}<br>强度 > 0 的特征数：%{y}<extra></extra>':
          'File: %{customdata[1]}<br>Current total intensity: %{x:.1e}<br>Features with intensity > 0: %{y}<extra></extra>',
        '特征=%{y}<br>列=%{x}<br>值=%{z:.3g}<extra></extra>':
          'Feature=%{y}<br>Column=%{x}<br>Value=%{z:.3g}<extra></extra>',
        '特征=%{y}<br>列=%{x}<br>强度=%{z:.1e}<extra></extra>':
          'Feature=%{y}<br>Column=%{x}<br>Intensity=%{z:.1e}<extra></extra>',
        '细胞：%{customdata[0]}<br>x：%{x:.2e}<br>y：%{y:.2e}<extra>%{fullData.name}</extra>':
          'Cell: %{customdata[0]}<br>x: %{x:.2e}<br>y: %{y:.2e}<extra>%{fullData.name}</extra>',
        '细胞 %{customdata[0]}<br>伪时间 %{customdata[1]}<extra></extra>':
          'Cell %{customdata[0]}<br>Pseudotime %{customdata[1]}<extra></extra>',
        '所选根点 %{customdata[0]}<extra></extra>': 'Selected root %{customdata[0]}<extra></extra>',
        '窗口 %{customdata[0]}<br>有效细胞 %{customdata[1]}<br>速度 %{y}<extra></extra>':
          'Window %{customdata[0]}<br>Valid cells %{customdata[1]}<br>Speed %{y}<extra></extra>',
        '窗口 %{customdata[0]}<br>时间中心 %{customdata[1]}<br>有效细胞 %{customdata[2]}<br>权重和 %{customdata[3]}<extra></extra>':
          'Window %{customdata[0]}<br>Time center %{customdata[1]}<br>Valid cells %{customdata[2]}<br>Weight sum %{customdata[3]}<extra></extra>',
        '%{customdata[2]} · %{y}<br>窗口 %{x}<br>时间 %{customdata[0]}<br>有限细胞 %{customdata[1]}<br>显示值 %{z}<extra></extra>':
          '%{customdata[2]} · %{y}<br>Window %{x}<br>Time %{customdata[0]}<br>Finite cells %{customdata[1]}<br>Display value %{z}<extra></extra>',
      }
      trace.hovertemplate = templates[trace.hovertemplate] ?? trace.hovertemplate
    }
    // Colorbar titles are generated for heatmaps and SHAP; observation/category
    // names on embedding and scatter plots are user input and remain untouched.
    if (key.includes('heatmap') || key.includes('shap') || key === 'time_plot') {
      const marker = trace.marker as Record<string, unknown> | undefined
      for (const bar of [trace.colorbar, marker?.colorbar])
        if (bar && typeof bar === 'object') title(bar as Record<string, unknown>)
    }
  }
  return figure
}
