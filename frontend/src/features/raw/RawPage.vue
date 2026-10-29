<script setup lang="ts">
import { useRawWorkbench } from './composables/useRawWorkbench'
import PlotView from '../../components/PlotView.vue'
import ProjectArtifacts from '../../components/ProjectArtifacts.vue'
import ProcessingFields from './ProcessingFields.vue'
import SignalDiagnostics from './SignalDiagnostics.vue'
const {
  store,
  auth,
  sample,
  opened,
  summary,
  parameters,
  effectiveParameters,
  applicationScope,
  differsFromCurrent,
  unapplied,
  kind,
  ms,
  scan,
  rtMin,
  rtMax,
  mzMin,
  mzMax,
  refs,
  ppm,
  fast,
  normalize,
  bins,
  plots,
  job,
  jobNote,
  cellCount,
  preferences,
  preferencesError,
  preferencesLoading,
  loadPreferences,
  preset,
  presetText,
  strategy,
  mergePpm,
  autoRanges,
  legacyParameters,
  samples,
  basic,
  expanded,
  parameterCategory,
  categories,
  category,
  navigateCategory,
  scanCatalog,
  scanTime,
  selectRange,
  selectedRange,
  scanPosition,
  currentPlot,
  seekScan,
  edited,
  open,
  plot,
  apply,
  clearParameters,
  startPreview,
  usePreset,
  savePresets,
} = useRawWorkbench()
</script>
<template>
  <section v-if="store.project">
    <div class="page-title">
      <div>
        <p class="eyebrow">STEP 02 / 原始谱</p>
        <h1>原始谱与参数</h1>
        <p>检查采集信号，选择实验参考离子，再预览细胞窗口。</p>
      </div>
      <span class="step-badge">02 / 06</span>
    </div>
    <div class="card raw-sample-toolbar">
      <div class="field-grid">
        <label
          ><FieldLabel name="当前样本" /><select
            aria-label="当前样本"
            v-model="sample"
            :disabled="store.busy"
          >
            <option value="" disabled>选择样本</option>
            <option v-for="s in samples" :key="s.id" :value="s.id">
              {{ s.name }}{{ s.parameters ? ' · 样本例外' : '' }}
            </option>
          </select></label
        >
      </div>
      <div class="actions">
        <button class="primary" :disabled="!sample || store.busy" @click="open">
          打开原始文件
        </button>
      </div>
      <details v-if="summary" class="raw-file-details">
        <summary>
          原始文件详情 · {{ summary.scan_count }} 扫描 · {{ summary.instrument || '仪器未标注' }}
        </summary>
        <dl class="detail-list">
          <div>
            <dt>原始文件</dt>
            <dd>{{ summary.path }}</dd>
          </div>
          <div>
            <dt>扫描 / 仪器</dt>
            <dd>{{ summary.scan_count }} / {{ summary.instrument || '—' }}</dd>
          </div>
          <div>
            <dt>RT / m/z</dt>
            <dd>
              {{ summary.rt_min_seconds }}–{{ summary.rt_max_seconds }} 秒 / {{ summary.mz_min }}–{{
                summary.mz_max
              }}
            </dd>
          </div>
        </dl>
      </details>
    </div>
    <div class="workflow-columns raw-workflow">
      <div class="card raw-parameter-panel">
        <h2>提取参数</h2>
        <p class="muted">参考离子须依据实验明确选择。显示范围单独设置。</p>
        <p class="method-badge">
          <FieldLabel
            name="提取方法：snr"
            text="固定使用 SNR 提取：按参考离子识别细胞窗口，扣除基线并以背景噪声衡量特征信号。内部标识 snr_v1 保留用于旧项目与产物兼容。"
          />
        </p>
        <p v-if="legacyParameters" class="alert">
          此项目或样本仍保存 legacy 参数。当前表单已切换为
          snr，请检查并应用参数后启动新提取；旧产物保留原算法记录。
        </p>
        <h3>当前表单 · 按应用范围生效</h3>
        <div class="reference-preset">
          <label
            ><FieldLabel name="Cell type" /><select
              aria-label="Cell type"
              v-model="preset"
              :disabled="store.busy"
            >
              <option v-for="(mass, name) in preferences?.presets" :key="name" :value="name">
                {{ name }} · {{ mass }}
              </option>
            </select></label
          >

          <button :disabled="store.busy" @click="usePreset">使用所选参考离子</button>
        </div>
        <p v-if="preferencesError" class="alert" role="alert">
          {{ preferencesError }}
          <button
            class="preview"
            :disabled="preferencesLoading || store.busy"
            @click="loadPreferences"
          >
            重试读取预设
          </button>
        </p>
        <ProcessingFields
          v-model="parameters"
          :fields="basic"
          :disabled="store.busy"
          @edited="edited"
        />
        <button
          type="button"
          class="parameter-toggle"
          :aria-expanded="expanded"
          aria-controls="extraction-advanced"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起扩展参数' : '展开全部参数' }}
          <span aria-hidden="true">{{ expanded ? '▴' : '▾' }}</span>
        </button>
        <section
          v-if="expanded"
          id="extraction-advanced"
          class="parameter-advanced"
          aria-label="分类提取参数"
        >
          <div class="parameter-categories" role="tablist" aria-label="参数分类">
            <button
              v-for="item in categories"
              :id="`parameter-tab-${item.key}`"
              :key="item.key"
              type="button"
              role="tab"
              :aria-selected="parameterCategory === item.key"
              :tabindex="parameterCategory === item.key ? 0 : -1"
              @keydown="navigateCategory"
              aria-controls="parameter-category-panel"
              :class="{ selected: parameterCategory === item.key }"
              @click="parameterCategory = item.key"
            >
              {{ item.label }}
            </button>
          </div>
          <div
            id="parameter-category-panel"
            role="tabpanel"
            :aria-labelledby="`parameter-tab-${parameterCategory}`"
          >
            <ProcessingFields
              v-model="parameters"
              :fields="category.fields"
              :disabled="store.busy"
              @edited="edited"
            />
            <div v-if="parameterCategory === 'reference'" class="parameter-controls">
              <label class="parameter-field"
                ><FieldLabel name="auto_ranges" /><select
                  aria-label="auto_ranges"
                  v-model="autoRanges"
                  :disabled="store.busy"
                  @change="edited"
                >
                  <option :value="true">启用自动范围</option>
                  <option :value="false">关闭自动范围</option>
                </select></label
              >
            </div>
            <p v-if="['merge', 'reference'].includes(parameterCategory)" class="muted">
              自动范围、样本合并策略及合并容差为项目级设置；不受仅当前样本的应用范围限制。
            </p>
            <div v-if="parameterCategory === 'merge'" class="parameter-controls">
              <label class="parameter-field"
                ><FieldLabel name="feature_strategy" /><select
                  aria-label="feature_strategy"
                  v-model="strategy"
                  :disabled="store.busy"
                  @change="edited"
                >
                  <option>shared</option>
                  <option>independent</option>
                </select></label
              >
              <label v-if="strategy === 'independent'" class="parameter-field"
                ><FieldLabel name="feature_merge_ppm" /><input
                  aria-label="feature_merge_ppm"
                  v-model.number="mergePpm"
                  type="number"
                  min="0"
                  step="any"
                  :disabled="store.busy"
                  @input="edited"
              /></label>
            </div>
            <template v-if="parameterCategory === 'presets'">
              <label class="field"
                ><FieldLabel name="预设名称与参考 m/z（JSON）" /><textarea
                  aria-label="预设名称与参考 m/z（JSON）"
                  v-model="presetText"
                  rows="5"
                  :disabled="store.busy"
                ></textarea>
              </label>
              <button v-if="auth.admin" class="save" :disabled="store.busy" @click="savePresets">
                保存全局预设
              </button>
            </template>
          </div>
        </section>
        <div class="parameter-state" :class="{ pending: unapplied }" aria-label="参数生效状态">
          <strong>{{
            unapplied
              ? '未应用草稿 · 与所选范围的生效配置不同'
              : store.project?.unsaved
                ? '已应用未保存 · 与所选范围的生效配置一致'
                : '已保存 · 与所选范围的生效配置一致'
          }}</strong>
          <p>
            当前样本使用{{
              samples.find((s) => s.id === sample)?.parameters ? '样本例外' : '项目默认及自动范围'
            }}。{{
              differsFromCurrent
                ? '表单与当前样本正式提取参数不同；预览使用表单参数。'
                : '表单与当前样本正式提取参数一致。'
            }}
          </p>
          <p v-if="applicationScope === 'sample'">
            样本合并策略、合并容差及自动范围仍为项目级设置。
          </p>
          <p>应用后仍需保存项目；已完成的提取结果保持原参数记录。</p>
        </div>
        <div class="actions parameter-apply-actions">
          <label class="application-scope"
            >应用范围<select
              aria-label="参数应用范围"
              v-model="applicationScope"
              :disabled="store.busy"
            >
              <option value="project">项目默认（保留样本例外）</option>
              <option value="sample">仅当前样本</option>
            </select></label
          >
          <button
            class="primary"
            :disabled="store.busy || (applicationScope === 'sample' && !sample)"
            @click="apply"
          >
            应用参数</button
          ><button class="restore" :disabled="!sample || store.busy" @click="clearParameters">
            清除样本例外</button
          ><button
            class="preview"
            :disabled="opened !== sample || !!job || store.busy"
            @click="startPreview"
          >
            预览细胞窗口
          </button>
        </div>
        <p v-if="jobNote" role="status">
          {{ jobNote }}；预览缓存写入服务器，不直接建立当前数据集。
        </p>
        <ProjectArtifacts scope="previews" :refresh-key="cellCount" />
      </div>
      <div class="card">
        <h2>原始信号</h2>
        <div class="tabs">
          <button
            v-for="(label, value) in {
              tic: 'TIC',
              eic: 'EIC',
              sum: '合并谱',
              single: '单扫描',
              cells: '细胞窗口',
            }"
            :key="value"
            :class="{ selected: kind === value }"
            @click="kind = value"
          >
            {{ label }}
          </button>
        </div>
        <div v-if="kind !== 'cells'" class="field-grid">
          <label
            ><FieldLabel name="MS level" /><input
              aria-label="MS level"
              v-model.number="ms"
              type="number"
              min="1"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="RT min（秒，空值全范围）" /><input
              aria-label="RT min（秒，空值全范围）"
              v-model="rtMin"
              type="number"
              :disabled="store.busy" /></label
          ><label
            ><FieldLabel name="RT max（秒）" /><input
              aria-label="RT max（秒）"
              v-model="rtMax"
              type="number"
              :disabled="store.busy" /></label
          ><template v-if="kind === 'eic'"
            ><label
              ><FieldLabel name="reference m/z" /><input
                aria-label="reference m/z"
                v-model="refs"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="ppm tolerance" /><input
                aria-label="ppm tolerance"
                v-model.number="ppm"
                type="number"
                step="any"
                :disabled="store.busy" /></label></template
          ><template v-if="kind === 'sum'"
            ><label
              ><FieldLabel name="display mz_min" /><input
                aria-label="display mz_min"
                v-model.number="mzMin"
                type="number"
                step="any"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="display mz_max" /><input
                aria-label="display mz_max"
                v-model.number="mzMax"
                type="number"
                step="any"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="合谱方式" /><select
                aria-label="合谱方式"
                v-model="fast"
                :disabled="store.busy"
              >
                <option :value="true">快速固定网格</option>
                <option :value="false">高分辨率合谱</option>
              </select></label
            ><label
              ><FieldLabel name="bins" /><input
                aria-label="bins"
                v-model.number="bins"
                type="number"
                :disabled="store.busy" /></label
            ><label
              ><FieldLabel name="normalize" /><select
                aria-label="normalize"
                v-model="normalize"
                :disabled="store.busy"
              >
                <option :value="false">求和</option>
                <option :value="true">平均</option>
              </select></label
            ></template
          ><label v-if="kind === 'single'"
            ><FieldLabel name="scan_index（从 0 开始）" /><input
              aria-label="scan_index（从 0 开始）"
              v-model.number="scan"
              type="number"
              min="0"
              :max="Number(summary?.scan_count ?? 1) - 1"
              :disabled="store.busy"
          /></label>
        </div>
        <div class="actions">
          <button
            v-if="kind !== 'cells'"
            class="primary"
            :disabled="opened !== sample || store.busy"
            @click="plot()"
          >
            更新图形</button
          ><button
            v-if="kind === 'single'"
            :disabled="scanPosition <= 0 || store.busy"
            @click="seekScan('step', -1)"
          >
            上一帧</button
          ><button
            v-if="kind === 'single'"
            :disabled="scanPosition >= scanCatalog.indices.length - 1 || store.busy"
            @click="seekScan('step', 1)"
          >
            下一帧</button
          ><button
            v-if="currentPlot"
            class="save"
            :disabled="store.busy"
            @click="store.download('raw', `${kind}.csv`, kind)"
          >
            下载完整数据 CSV
          </button>
        </div>
        <div v-if="kind === 'single' && scanCatalog.indices.length" class="field-grid">
          <label
            ><FieldLabel name="scan time（秒）" /><input
              aria-label="scan time（秒）"
              :value="scanTime"
              type="number"
              step="any"
              :disabled="store.busy"
              @change="
                seekScan('time', Number(($event.target as HTMLInputElement).value))
              " /></label
          ><label
            ><FieldLabel name="时间滑块" /><input
              aria-label="时间滑块"
              :value="scanTime"
              type="range"
              :min="scanCatalog.times[0]"
              :max="scanCatalog.times.at(-1)"
              step="any"
              :disabled="store.busy"
              @change="seekScan('time', Number(($event.target as HTMLInputElement).value))"
          /></label>
        </div>
        <p v-if="cellCount !== undefined && kind === 'cells'">
          检出 {{ cellCount }} 个细胞；预览不会直接建立当前数据。
        </p>
        <dl
          v-if="currentPlot?.detail && Object.keys(currentPlot.detail).length"
          class="detail-list"
        >
          <div v-for="(value, key) in currentPlot.detail" :key="key">
            <dt>{{ key }}</dt>
            <dd>{{ value }}</dd>
          </div>
        </dl>
        <label v-if="['tic', 'eic', 'cells'].includes(kind)"
          ><FieldLabel name="拖动方式" /><select
            aria-label="拖动方式"
            v-model="selectRange"
            :disabled="store.busy"
          >
            <option :value="false">缩放</option>
            <option :value="true">选择合谱范围</option>
          </select></label
        >
        <PlotView
          v-if="currentPlot"
          :key="kind"
          :figure="currentPlot.figure"
          :name="`raw-${kind}`"
          :select-range="selectRange && ['tic', 'eic', 'cells'].includes(kind)"
          @range="selectedRange"
        />
        <p v-else class="muted">打开样本并生成图形后显示。</p>
      </div>
    </div>
    <SignalDiagnostics :sample="sample" :opened="opened" />
  </section>
  <div v-else class="card empty-state">
    <h1>请先打开项目</h1>
    <RouterLink to="/projects">前往项目首页 →</RouterLink>
  </div>
</template>
