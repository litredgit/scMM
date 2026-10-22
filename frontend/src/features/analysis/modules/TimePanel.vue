<script setup lang="ts">
import { useTimeAnalysis } from '../composables/useTimeAnalysis'
import PlotView from '../../../components/PlotView.vue'
import DataTable from '../../../components/DataTable.vue'
const tableNames: Record<string, string> = {
  cells: '细胞',
  windows: '窗口',
  multiscale: '多尺度坐标',
}
const {
  store,
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
</script>
<template>
  <div class="card analysis-module-split">
    <section class="analysis-calculation">
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
      <fieldset v-else :disabled="store.busy">
        <legend>窗口轨迹输入</legend>
        <div class="field-grid">
          <label
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
          <label
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
              min="1"
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
          <label
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
      <button
        class="primary"
        :disabled="
          store.busy ||
          !form.key ||
          (form.mode === 'palantir'
            ? !form.root_cell_id || !form.input_representation
            : !form.coordinate_key || !form.time_key || !form.time_kind || !form.unit)
        "
        @click="calculate"
      >
        计算并应用时间结果
      </button>
      <p class="muted">
        同步工程上限为 5000 细胞、500 万当前矩阵/输入表示数值、64 个命名结果和累计 500
        万结果数值；不是实验推荐阈值。当前在请求内计算，超时不自动重放。
      </p>
    </section>
    <section class="analysis-visualization">
      <h3>已有时间结果</h3>
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
      <p>
        读取表、绘图和导出复用有效的已计算数值，不重跑 Palantir
        或窗口计算。科学输入或依赖改变后过期结果不可下载。
      </p>
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
        <button class="download" :disabled="store.busy || !selected?.valid" @click="download">
          下载完整时间结果 ZIP
        </button>
      </div>
      <p v-if="figureMeta.time_result_key">图来源结果：{{ figureMeta.time_result_key }}</p>
      <p v-for="note in figureMeta.notes ?? []" :key="note">{{ note }}</p>
      <PlotView v-if="figure" :figure="figure" name="time_plot" />
      <template v-if="result"
        ><h4>结果 {{ result.key }} 的生效参数</h4>
        <pre>{{ JSON.stringify(result.parameters, null, 2) }}</pre>
        <section v-for="(table, name) in result.tables" :key="name">
          <h4>
            {{ tableNames[name] ?? name }}
            · 共 {{ table.total }} 行（页面至多 200 行）
          </h4>
          <DataTable :table="table" />
        </section>
      </template>
    </section>
  </div>
</template>
