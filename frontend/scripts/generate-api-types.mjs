import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import openapiTS, { astToString } from 'openapi-typescript'

const root = new URL('../../', import.meta.url)
const schema = execFileSync('uv', ['run', '--no-sync', 'python', 'scripts/export_openapi.py'], {
  cwd: root,
  encoding: 'utf8',
})
const output = new URL('../src/api/openapi.generated.d.ts', import.meta.url)
writeFileSync(output, astToString(await openapiTS(JSON.parse(schema))))
