<script setup lang="ts">
import CalculationPanel from '../components/CalculationPanel.vue'
import SectionNav from '../../../components/SectionNav.vue'
import { computed } from 'vue'
import { useTimeAnalysis } from '../composables/useTimeAnalysis'
import PlotView from '../../../components/PlotView.vue'
import DataTable from '../../../components/DataTable.vue'
const tableNames: Record<string, string> = {
  cells: '细胞',
  windows: '窗口',
  multiscale: '多尺度坐标',
  features: '特征',
  trends: '窗口特征趋势',
  statistics: '特征趋势统计',
  curves: '聚类成员完整曲线',
  distances: '聚类特征距离',
}
const {
  store,
  selectedFeatures,
  form,
  info,
  result,
  figure,
  search,
  readError,
  selected,
  figureMeta,
  load,
  calculate,
  readResult,
  draw,
  download,
} = useTimeAnalysis()
const nameConflict = computed(() => info.value?.results.some((row) => row.key === form.key))
const trendFeatures = computed({
  get: () => form.features.join('\n'),
  set: (value: string) => {
    form.features = value
      .split(/[\n,;]+/)
      .map((v) => v.trim())
      .filter(Boolean)
  },
})
</script>
<template>
  <div class="card analysis-module-split">
    <SectionNav
      :items="[
        { id: 'time-compute', label: '新建时间计算' },
        { id: 'time-results', label: '查看命名结果' },
        { id: 'time-export', label: '下载完整结果' },
      ]"
    />
    <CalculationPanel
      result-target="time-results"
      id="time-compute"
      :has-result="!!info?.results.some((row) => row.valid)"
    >
      <h2>伪时间与窗口轨迹</h2>
      <p>
        根点依据实验先验明确选择。采集进程、实验时间与伪时间不可混用。每次结果独立命名，不覆盖旧键；改草稿不改已计算结果。
      </p>
      <p v-if="readError" role="alert">{{ readError }}</p>
      <button class="preview" :disabled="store.busy" @click="load">刷新时间分析状态</button>
      <div class="field-grid">
        <label
          ><FieldLabel
            name="时间分析方法"
            help-key="operation"
            text="Palantir 输出伪时间/分支概率；窗口轨迹只计算排序窗口的加权坐标中心。"
          />
          <select v-model="form.mode" aria-label="时间分析方法" :disabled="store.busy">
            <option value="palantir">Palantir 伪时间</option>
            <option value="trajectory">滑动窗口轨迹</option>
            <option value="velocity">窗口代谢速度</option>
            <option value="trends">代谢物窗口趋势</option>
            <option value="trend_clusters">趋势聚类</option>
          </select>
        </label>
        <label
          ><FieldLabel
            name="时间结果输出键"
            help-key="key"
            text="字母开头，至多 48 位字母/数字/下划线；已存在或失效旧键均不覆盖。" /><input
            v-model="form.key"
            aria-label="时间结果输出键"
            :disabled="store.busy"
        /></label>
      </div>
      <fieldset v-if="form.mode === 'palantir'" :disabled="store.busy">
        <legend>Palantir 输入</legend>
        <label
          ><FieldLabel
            name="稳定细胞 ID 搜索"
            help-key="root_cell_id"
            text="搜索只展示候选 ID，不自动指定根点。" /><input
            v-model="search"
            aria-label="时间根点搜索"
        /></label>
        <button class="preview" @click="load">搜索稳定细胞 ID</button>
        <p>
          当前搜索 {{ info?.total_cells ?? 0 }} 个匹配，展示前
          {{ info?.cells.length ?? 0 }} 个；根点按精确 ID 校验。
        </p>
        <div class="field-grid">
          <label
            ><FieldLabel
              name="根点细胞 ID"
              help-key="root_cell_id"
              text="不是显示行号；依据实验先验选择稳定细胞 ID。" /><input
              v-model="form.root_cell_id"
              list="time-root-cells"
              aria-label="根点细胞 ID"
              placeholder="明确选择稳定 ID"
          /></label>
          <datalist id="time-root-cells">
            <option v-for="id in info?.cells" :key="id" :value="id" />
          </datalist>
          <label
            ><FieldLabel
              name="Palantir 输入表示"
              help-key="input_representation"
              text="直接输入当前矩阵/强度层或已有嵌入；不自动缩放或替你选择 PCA。"
            /><select v-model="form.input_representation" aria-label="Palantir 输入表示">
              <option value="" disabled>明确选择输入表示</option>
              <option value="X">矩阵 / 强度层</option>
              <option v-for="key in info?.embeddings" :key="key" :value="key">{{ key }}</option>
            </select></label
          >
          <label v-if="form.input_representation === 'X'"
            ><FieldLabel
              name="Palantir 强度层"
              help-key="layer"
              text="空值使用当前 X；层必须明确存在。"
            /><select v-model="form.layer" aria-label="Palantir 强度层">
              <option :value="null">当前矩阵 X</option>
              <option v-for="key in info?.layers" :key="key">{{ key }}</option>
            </select></label
          >
        </div>
        <label
          ><FieldLabel
            name="终末细胞 ID"
            help-key="terminal_cell_ids"
            text="每行一个精确 ID；留空由算法推断，不自动选择末行细胞。"
          /><textarea v-model="form.terminal_cell_ids" aria-label="终末细胞 ID" rows="3" />
        </label>
        <div class="field-grid">
          <label
            ><FieldLabel
              name="扩散成分数"
              help-key="n_diff_components"
              text="2–100，须小于细胞数减 1。" /><input
              type="number"
              min="2"
              max="100"
              step="1"
              v-model.number="form.n_diff_components"
              aria-label="扩散成分数"
          /></label>
          <label
            ><FieldLabel
              name="Palantir 近邻数"
              help-key="knn"
              text="至少 3，须小于细胞数；断连扩散核拒绝，不人为补边。" /><input
              type="number"
              min="3"
              step="1"
              v-model.number="form.knn"
              aria-label="Palantir 近邻数"
          /></label>
          <label
            ><FieldLabel
              name="路标数量"
              help-key="num_waypoints"
              text="不少于 3 和扩散成分数，不超过细胞数；默认沿用 Python 入口，少细胞须明确调整。" /><input
              type="number"
              min="3"
              step="1"
              v-model.number="form.num_waypoints"
              aria-label="路标数量"
          /></label>
          <label
            ><FieldLabel
              name="伪时间迭代上限"
              help-key="max_iterations"
              text="保留现有 Palantir 迭代定义。" /><input
              type="number"
              min="1"
              max="1000"
              step="1"
              v-model.number="form.max_iterations"
              aria-label="伪时间迭代上限"
          /></label>
          <label
            ><FieldLabel
              name="时间分析随机种子"
              help-key="seed"
              text="记录种子、库版本与输入身份；跨版本不承诺逐位一致。" /><input
              type="number"
              min="0"
              step="1"
              v-model.number="form.seed"
              aria-label="时间分析随机种子"
          /></label>
          <label
            ><FieldLabel name="缩放扩散成分" help-key="scale_components" /><input
              type="checkbox"
              v-model="form.scale_components"
              aria-label="缩放扩散成分"
          /></label>
          <label
            ><FieldLabel
              name="固定所选根点"
              help-key="use_early_cell_as_start"
              text="关闭时算法可选择邻近边界点，结果记录实际最早细胞。" /><input
              type="checkbox"
              v-model="form.use_early_cell_as_start"
              aria-label="固定所选根点"
          /></label>
        </div>
      </fieldset>
      <fieldset v-else-if="form.mode !== 'trend_clusters'" :disabled="store.busy">
        <legend>
          {{
            form.mode === 'velocity'
              ? '窗口代谢速度输入'
              : form.mode === 'trends'
                ? '代谢物趋势输入'
                : '窗口轨迹输入'
          }}
        </legend>
        <p v-if="form.mode === 'velocity'">
          沿递增时间回归特征强度，输出带符号斜率及向量范数；不是同位素示踪代谢通量。时间、强度层和尺度影响单位，相同时间窗口保留为空。
        </p>
        <div class="field-grid">
          <label v-if="form.mode === 'trajectory'"
            ><FieldLabel
              name="轨迹坐标"
              help-key="coordinate_key"
              text="至少二维；窗口按全部坐标维度加权，图显示前两维。"
            /><select v-model="form.coordinate_key" aria-label="轨迹坐标">
              <option value="" disabled>明确选择坐标</option>
              <option v-for="key in info?.embeddings" :key="key">{{ key }}</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="轨迹时间列"
              help-key="time_key"
              text="明确选择数值列；自动提取的 time 是归一化采集进程。"
            /><select v-model="form.time_key" aria-label="轨迹时间列">
              <option value="" disabled>明确选择时间列</option>
              <option v-for="key in info?.observations" :key="key">{{ key }}</option>
            </select></label
          >
          <label
            ><FieldLabel name="轨迹时间含义" help-key="time_kind" /><select
              v-model="form.time_kind"
              aria-label="轨迹时间含义"
            >
              <option value="" disabled>明确声明含义</option>
              <option value="normalized_time">归一化采集进程（0–1）</option>
              <option value="acquisition_seconds">采集坐标（秒）</option>
              <option value="experimental_time">自定义实验时间</option>
              <option value="pseudotime">伪时间（算法尺度）</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="轨迹时间单位"
              help-key="unit"
              text="归一化/伪时间为 unitless，采集秒数为 s；自定义实验时间必须显式填写单位。" /><input
              v-model="form.unit"
              aria-label="轨迹时间单位"
              :disabled="form.time_kind !== 'experimental_time'"
          /></label>
          <label v-if="form.mode === 'velocity' || form.mode === 'trends'"
            ><FieldLabel
              :name="form.mode === 'trends' ? '趋势强度层' : '速度强度层'"
              help-key="layer"
              text="使用当前 X 或明确选择已有强度层；强度尺度影响统计结果，不自动归一化。"
            /><select
              v-model="form.layer"
              :aria-label="form.mode === 'trends' ? '趋势强度层' : '速度强度层'"
            >
              <option :value="null">当前 X</option>
              <option v-for="key in info?.layers" :key="key">{{ key }}</option>
            </select></label
          >
          <label v-if="form.mode === 'trajectory'"
            ><FieldLabel
              name="分支概率"
              help-key="branch_probability_key"
              text="留空按单分支等权；显式键缺失或概率无效拒绝，不静默回退。"
            /><select v-model="form.branch_probability_key" aria-label="轨迹分支概率">
              <option :value="null">单分支等权</option>
              <option v-for="key in info?.probability_keys" :key="key">{{ key }}</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="时间窗口细胞数"
              help-key="window_size"
              text="单位是细胞数，超过总细胞数时沿用原方法截断并记录实际值。" /><input
              type="number"
              :min="form.mode === 'velocity' ? 2 : 1"
              max="5000"
              step="1"
              v-model.number="form.window_size"
              aria-label="时间窗口细胞数"
          /></label>
          <label
            ><FieldLabel name="窗口步长细胞数" help-key="step_size" /><input
              type="number"
              min="1"
              max="5000"
              step="1"
              v-model.number="form.step_size"
              aria-label="窗口步长细胞数"
          /></label>
          <label v-if="form.mode === 'trajectory'"
            ><FieldLabel
              name="每窗口最少有效细胞"
              help-key="min_cells_per_window"
              text="非有限坐标不计入有效细胞；不足的窗口保留为空。" /><input
              type="number"
              min="1"
              max="5000"
              step="1"
              v-model.number="form.min_cells_per_window"
              aria-label="每窗口最少有效细胞"
          /></label>
        </div>
      </fieldset>
      <fieldset v-if="form.mode === 'trends'" :disabled="store.busy">
        <legend>趋势特征与统计</legend>
        <label
          ><FieldLabel
            name="趋势特征 ID"
            help-key="features"
            text="空白使用全部稳定 ID；每行一个，不做最近 m/z 匹配。选择范围也是 BH 校正的特征范围。"
          />
          <textarea v-model="trendFeatures" aria-label="趋势特征 ID" rows="4" />
        </label>
        <button class="preview" @click="form.features = [...selectedFeatures]">
          使用已选趋势特征
        </button>
        <div class="field-grid">
          <label
            ><FieldLabel
              name="趋势名称来源"
              help-key="feature_name_key"
              text="明确选择特征元数据列；缺失名称回退到稳定 ID，重名仍显示 ID。"
            /><select v-model="form.feature_name_key" aria-label="趋势名称来源">
              <option :value="null">稳定特征 ID</option>
              <option v-for="key in info?.feature_columns" :key="key">{{ key }}</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="趋势窗口统计"
              help-key="kernel_stat"
              text="保留现有 median/mean/sum；忽略 NaN，全空的中位数/均值未定义，总和为 0，结合有限细胞数解释。"
            /><select v-model="form.kernel_stat" aria-label="趋势窗口统计">
              <option value="median">中位数</option>
              <option value="mean">均值</option>
              <option value="sum">总和</option>
            </select></label
          >
        </div>
        <p>
          时间列及含义须明确选择；重叠窗口不独立，Spearman/BH
          仅作探索排序，细胞数不是生物重复。计算不标准化源矩阵。
        </p>
      </fieldset>
      <fieldset v-if="form.mode === 'trend_clusters'" :disabled="store.busy">
        <legend>趋势聚类输入</legend>
        <p>
          依赖有效的已计算趋势，不重新计算窗口统计。沿现有方法先标准化曲线；常量保持
          0，无跨窗口有限趋势的特征标为 -1。分组仅用于探索，不是代谢通路或因果证据。
        </p>
        <div class="field-grid">
          <label
            ><FieldLabel
              name="聚类来源趋势"
              help-key="trend_key"
              text="只接受当前有效的命名代谢物窗口趋势；来源或依赖失效时聚类也失效。"
            /><select v-model="form.trend_key" aria-label="聚类来源趋势">
              <option value="" disabled>明确选择有效趋势</option>
              <option
                v-for="row in info?.results.filter((row) => row.kind === 'trends' && row.valid)"
                :key="row.key"
                :value="row.key"
              >
                {{ row.key }}
              </option>
            </select></label
          >
          <label
            ><FieldLabel name="趋势聚类方法" help-key="cluster_method" /><select
              v-model="form.trend_cluster_method"
              aria-label="趋势聚类方法"
            >
              <option value="leiden">Leiden</option>
              <option value="louvain">Louvain</option>
              <option value="kmeans">KMeans</option>
              <option value="agglomerative">层次聚类</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="趋势聚类距离"
              help-key="metric"
              text="沿原算法使用标准化曲线；KMeans 的归一化和 Ward 的欧氏空间另在生效参数记录。"
            /><select v-model="form.trend_metric" aria-label="趋势聚类距离">
              <option value="correlation">相关距离</option>
              <option value="cosine">余弦距离</option>
              <option value="euclidean">欧氏距离</option>
              <option value="sqeuclidean">平方欧氏距离</option>
            </select></label
          >
          <label
            ><FieldLabel
              name="趋势排名前 N 项"
              help-key="top_k"
              text="留空按来源特征顺序使用全部；填写时使用既有趋势排名。同步最多 500 特征，不静默截断。" /><input
              :value="form.top_k ?? ''"
              @input="
                form.top_k =
                  ($event.target as HTMLInputElement).value === ''
                    ? null
                    : Number(($event.target as HTMLInputElement).value)
              "
              type="number"
              min="1"
              max="500"
              aria-label="趋势排名前 N 项"
          /></label>
          <label v-if="form.trend_cluster_method !== 'agglomerative'"
            ><FieldLabel
              name="趋势聚类随机种子"
              help-key="seed"
              text="0–2³¹−1；随机方法在隔离进程内设置随机源，不影响其他用户。单个有效特征直接成组，不随机拟合。" /><input
              v-model.number="form.cluster_seed"
              type="number"
              min="0"
              max="2147483647"
              aria-label="趋势聚类随机种子"
          /></label>
          <label v-if="['kmeans', 'agglomerative'].includes(form.trend_cluster_method)"
            ><FieldLabel
              name="趋势簇数"
              help-key="n_clusters"
              text="1 至有效特征数；KMeans 实际簇数不足时记录警告，不当作请求簇数已达到。" /><input
              v-model.number="form.trend_n_clusters"
              type="number"
              min="1"
              max="500"
              aria-label="趋势簇数"
          /></label>
          <label v-if="['leiden', 'louvain'].includes(form.trend_cluster_method)"
            ><FieldLabel
              name="趋势图近邻数"
              help-key="n_neighbors"
              text="沿原算法按有效特征数截断，记录请求值和实际值。" /><input
              v-model.number="form.trend_n_neighbors"
              type="number"
              min="1"
              max="499"
              aria-label="趋势图近邻数"
          /></label>
          <label v-if="form.trend_cluster_method === 'leiden'"
            ><FieldLabel
              name="趋势图分辨率"
              help-key="resolution"
              text="正数，仅用于 Leiden，保留原 RBConfiguration 分区。" /><input
              v-model.number="form.trend_resolution"
              type="number"
              min="0"
              step="0.1"
              aria-label="趋势图分辨率"
          /></label>
          <label v-if="form.trend_cluster_method === 'agglomerative'"
            ><FieldLabel
              name="趋势层次连接"
              help-key="linkage"
              text="Ward 仅允许欧氏类距离；拟合直接使用标准化曲线的欧氏空间。"
            /><select v-model="form.trend_linkage" aria-label="趋势层次连接">
              <option value="average">平均连接</option>
              <option value="complete">完全连接</option>
              <option value="single">单连接</option>
              <option value="ward">Ward</option>
            </select></label
          >
        </div>
        <p>
          常量曲线的相关/余弦距离可能未定义，沿原算法以矩阵最大有限距离（含对角线
          0）替代，结果记录替代数量。趋势聚类最多一个短进程，90
          秒超时后终止并回收；当前仍在请求内等待，超时不自动重放。
        </p>
      </fieldset>
      <p v-if="nameConflict" class="state-note" role="status">
        结果名称 {{ form.key }} 已占用，请换一个名称；旧结果保留。
      </p>
      <button
        class="primary"
        :disabled="
          store.busy ||
          nameConflict ||
          !form.key ||
          (form.mode === 'palantir'
            ? !form.root_cell_id || !form.input_representation
            : form.mode === 'trend_clusters'
              ? !form.trend_key
              : (form.mode === 'trajectory' && !form.coordinate_key) ||
                !form.time_key ||
                !form.time_kind ||
                !form.unit ||
                (form.mode === 'velocity' && form.window_size < 2))
        "
        @click="calculate"
      >
        计算并应用时间结果
      </button>
      <p class="muted">
        同步工程上限为 5000 细胞、500 万当前矩阵/输入表示数值、64 个命名结果和累计 500
        万结果数值；不是实验推荐阈值。当前在请求内计算，超时不自动重放。
      </p>
    </CalculationPanel>
    <section id="time-results" class="analysis-visualization task-section">
      <h3>已有时间结果</h3>
      <p class="result-state" role="status">
        {{
          !selected
            ? '无所选结果：选择已有命名结果，或新建计算。'
            : selected.valid
              ? '有效：查看、绘图与下载复用已记录结果，计算草稿另行应用。'
              : '已失效：数据或依赖已改变，需以新名称重算；该结果不可下载。'
        }}
      </p>
      <label
        >选择命名结果<select
          v-model="form.selected_result"
          aria-label="选择命名时间结果"
          :disabled="store.busy"
        >
          <option value="">选择已有结果</option>
          <option v-for="row in info?.results" :key="row.key" :value="row.key">
            {{ row.key }} · {{ row.kind }}{{ row.valid ? '' : '（已失效）' }}
          </option>
        </select></label
      >

      <label v-if="selected?.kind === 'palantir'"
        >时间图绘图坐标<select
          v-model="form.plot_coordinate_key"
          aria-label="时间图绘图坐标"
          :disabled="store.busy"
        >
          <option value="" disabled>明确选择显示坐标</option>
          <option v-for="key in info?.embeddings" :key="key">{{ key }}</option>
        </select></label
      >
      <details v-if="selected?.kind === 'trends'">
        <summary>趋势热图显示设置</summary>
        <fieldset :disabled="store.busy">
          <legend>趋势热图显示</legend>
          <label
            ><FieldLabel
              name="趋势显示特征数"
              help-key="plot_top_n"
              text="按已计算的 q 值及相关性排名；只限制热图，不截断完整下载。最多 500 个特征、20 万显示值。" /><input
              v-model.number="form.plot_top_n"
              type="number"
              min="1"
              max="500"
              aria-label="趋势显示特征数"
          /></label>
          <label
            ><FieldLabel
              name="趋势显示行标准分"
              help-key="display_standardize"
              text="仅对各特征窗口值做总体标准差的行标准分，常量行显示 0；不修改原趋势值或重新计算。" /><input
              v-model="form.display_standardize"
              type="checkbox"
              aria-label="趋势显示行标准分"
          /></label>
        </fieldset>
      </details>
      <div class="actions">
        <button class="preview" :disabled="store.busy || !selected?.valid" @click="readResult">
          读取时间结果表
        </button>
        <button
          class="primary"
          :disabled="
            store.busy ||
            !selected?.valid ||
            (selected.kind === 'palantir' && !form.plot_coordinate_key)
          "
          @click="draw()"
        >
          绘制时间结果
        </button>
        <button
          v-if="info?.saved_plot_key === form.selected_result"
          class="preview"
          :disabled="store.busy || !selected?.valid"
          @click="draw(true)"
        >
          读取已保存时间图
        </button>
      </div>
      <p v-if="figureMeta.time_result_key">图来源结果：{{ figureMeta.time_result_key }}</p>
      <PlotView v-if="figure" :figure="figure" name="time_plot" />
      <details v-if="figureMeta.notes?.length">
        <summary>结果说明与注意事项</summary>
        <p v-for="note in figureMeta.notes" :key="note">{{ note }}</p>
      </details>
      <section id="time-export" class="task-section">
        <h3>下载完整时间结果</h3>
        <button class="download" :disabled="store.busy || !selected?.valid" @click="download">
          下载完整时间结果 ZIP
        </button>
        <p class="muted">下载完整表格与参数，不替代保存项目；结果无效或尚未选择时不可下载。</p>
      </section>
      <template v-if="result"
        ><h4>结果 {{ result.key }} 的生效参数</h4>
        <details>
          <summary>查看生效参数</summary>
          <pre>{{ JSON.stringify(result.parameters, null, 2) }}</pre>
        </details>
        <details v-for="(table, name) in result.tables" :key="name">
          <summary>
            <h4>
              {{ tableNames[name] ?? name }}
              · 共 {{ table.total }} 行（页面至多 200 行）
            </h4>
          </summary>
          <DataTable :table="table" />
        </details>
      </template>
    </section>
  </div>
</template>
