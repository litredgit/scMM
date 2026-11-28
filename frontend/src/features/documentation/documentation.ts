import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import { authenticatedFetch } from '../../api/client'

const inputRoot = '../../../../'
const documents = import.meta.glob<string>(
  ['../../../../docs/{projects-and-data,extraction,annotation,statistics}.md'],
  { eager: true, import: 'default', query: '?url&no-inline' },
)
const diagrams = import.meta.glob<string>('../../../../docs/images/*.svg', {
  eager: true,
  import: 'default',
  query: '?url&no-inline',
})
export const documentIndex = 'docs/README.md'
const projectGuide = 'docs/projects-and-data.md'
const extractionGuide = 'docs/extraction.md'
const annotationGuide = 'docs/annotation.md'
const statisticsGuide = 'docs/statistics.md'
export const appendix = 'docs/appendix/README.md'
const referenceDocuments = new Set([
  'README.md',
  'AGENTS.md',
  'CHANGELOG.md',
  documentIndex,
  'docs/deployment.md',
  'docs/development.md',
  'docs/internal-reference.md',
  'docs/method-plugins.md',
  appendix,
  'docs/appendix/lipid-rule-review.md',
  'docs/appendix/statistical-method-notes.md',
  'docs/validation/README.md',
])
export const guides = [
  { file: projectGuide, title: '项目与数据' },
  { file: extractionGuide, title: '细胞提取' },
  { file: annotationGuide, title: '特征注释' },
  { file: statisticsGuide, title: '统计分析' },
]

export type DocumentLocation = { file: string; anchor?: string }
type Section = { anchor: string; title: string }
export type RenderedDocument = { file: string; html: string; sections: Section[] }

const pageGuides: Record<string, DocumentLocation> = {
  '/projects': { file: projectGuide, anchor: '登录与工作区' },
  '/cell-extraction': { file: extractionGuide, anchor: '添加文件与选择样本' },
  '/samples': { file: extractionGuide, anchor: '添加文件与选择样本' },
  '/raw': { file: extractionGuide, anchor: '预览与应用参数' },
  '/extraction': { file: extractionGuide, anchor: '提取停止与审核' },
  '/annotation': { file: annotationGuide, anchor: '候选与关系审核' },
  '/annotation/evidence': { file: annotationGuide, anchor: '证据与导入' },
  '/ions': { file: annotationGuide, anchor: '离子归组与化合物证据' },
  '/statistics': { file: statisticsGuide, anchor: '选择分析与核对结果' },
  '/data-check': { file: statisticsGuide, anchor: '数据检查与数据编辑' },
  '/data-editor': { file: statisticsGuide, anchor: '数据检查与数据编辑' },
  '/preprocess': { file: statisticsGuide, anchor: '预处理与-qc' },
  '/analysis': { file: statisticsGuide, anchor: '选择分析与核对结果' },
  '/results': { file: projectGuide, anchor: '图表作图数据和报告' },
  '/parameters': { file: projectGuide, anchor: '网页帮助与按钮' },
}

export function guideForPage(page: string): DocumentLocation {
  return pageGuides[page] ?? { file: documentIndex }
}

export function sectionId(anchor: string) {
  return `project-docs-section-${anchor}`
}

const docOrigin = 'https://scmm-docs.invalid'
const sourceRepository = 'https://github.com/litredgit/scMM/blob/main'
const markdown = new MarkdownIt({ html: false, linkify: false })

function sourceUrl(href: string, file: unknown) {
  if (typeof file !== 'string') return undefined
  try {
    const url = new URL(href, `${docOrigin}/${file}`)
    const local = url.origin === docOrigin && !/^(?:[a-z][a-z\d+.-]*:|\/\/)/i.test(href)
    return {
      url,
      path: local ? decodeURIComponent(url.pathname.slice(1)) : undefined,
      anchor: local ? decodeURIComponent(url.hash.slice(1)) : undefined,
    }
  } catch {
    return undefined
  }
}

markdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  const token = tokens[index]
  const target = sourceUrl(String(token.attrGet('href') ?? ''), env?.file)
  if (!target) return '<a>'
  const { url, path, anchor } = target
  if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return '<a>'

  if (path !== undefined) {
    const file = path.endsWith('/') || !path ? `${path}README.md` : path
    if (documents[inputRoot + file] || referenceDocuments.has(file)) {
      token.attrSet('data-document', file)
      if (anchor) token.attrSet('data-section', anchor)
      token.attrSet('href', anchor ? `#${sectionId(anchor)}` : '#project-docs-content')
      return renderer.renderToken(tokens, index, options)
    }
    const diagram = diagrams[inputRoot + path]
    token.attrSet('href', diagram ?? `${sourceRepository}${url.pathname}${url.search}${url.hash}`)
  }
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return renderer.renderToken(tokens, index, options)
}

const renderImage = markdown.renderer.rules.image!
markdown.renderer.rules.image = (tokens, index, options, env, renderer) => {
  const token = tokens[index]
  const source = sourceUrl(String(token.attrGet('src') ?? ''), env?.file)
  const diagram = source?.path && diagrams[inputRoot + source.path]
  if (!diagram) return markdown.utils.escapeHtml(token.content)
  token.attrSet('src', diagram)
  return renderImage(tokens, index, options, env, renderer)
}

export async function loadDocument(file: string, signal: AbortSignal): Promise<RenderedDocument> {
  const asset = documents[inputRoot + file]
  if (!asset && !referenceDocuments.has(file)) throw new Error('Unknown project document')
  const response = asset
    ? await fetch(asset, { signal })
    : await authenticatedFetch(`/api/v1/documentation/${file}`, { signal })
  if (!response.ok) throw new Error('Project document unavailable')

  const env = { file }
  const tokens = markdown.parse(await response.text(), env)
  const usedAnchors = new Set<string>()
  const sections: Section[] = []
  for (const [index, token] of tokens.entries()) {
    if (token.type !== 'heading_open') continue
    const inline = tokens[index + 1]
    const title = inline.children?.map((child) => child.content).join('') ?? inline.content
    const base =
      inline.content
        .toLowerCase()
        .replace(/[^\p{L}\p{N}_ -]/gu, '')
        .replaceAll(' ', '-') || 'section'
    let anchor = base
    for (let duplicate = 1; usedAnchors.has(anchor); duplicate++) anchor = `${base}-${duplicate}`
    usedAnchors.add(anchor)
    token.attrSet('id', sectionId(anchor))
    token.attrSet('tabindex', '-1')
    if (token.tag === 'h2') sections.push({ anchor, title })
  }

  const html = DOMPurify.sanitize(markdown.renderer.render(tokens, markdown.options, env), {
    ALLOWED_TAGS: [
      'a',
      'blockquote',
      'br',
      'code',
      'em',
      'h1',
      'h2',
      'h3',
      'h4',
      'h5',
      'h6',
      'hr',
      'img',
      'li',
      'ol',
      'p',
      'pre',
      's',
      'strong',
      'table',
      'tbody',
      'td',
      'th',
      'thead',
      'tr',
      'ul',
    ],
    ALLOWED_ATTR: [
      'alt',
      'class',
      'data-document',
      'data-section',
      'href',
      'id',
      'rel',
      'src',
      'start',
      'tabindex',
      'target',
      'title',
    ],
    ALLOW_ARIA_ATTR: false,
    ALLOW_DATA_ATTR: false,
  })
  return { file, html, sections }
}
