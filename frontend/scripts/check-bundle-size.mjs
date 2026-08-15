import { readdir, readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { gzipSync } from 'node:zlib'

const KIB = 1024
const assetsDirectory = resolve(process.cwd(), 'dist/assets')
const maxRawBytes = parseBudget('CYGNUS_MAX_JS_CHUNK_BYTES', 450 * KIB)
const maxGzipBytes = parseBudget('CYGNUS_MAX_JS_CHUNK_GZIP_BYTES', 140 * KIB)

const entries = await readdir(assetsDirectory, { withFileTypes: true }).catch((error) => {
  throw new Error(`Cannot inspect built assets at ${assetsDirectory}: ${error.message}`)
})
const javascriptFiles = entries
  .filter((entry) => entry.isFile() && entry.name.endsWith('.js'))
  .map((entry) => entry.name)

if (javascriptFiles.length === 0) {
  throw new Error(`No JavaScript chunks found in ${assetsDirectory}; run npm run build first`)
}

const chunks = await Promise.all(
  javascriptFiles.map(async (name) => {
    const content = await readFile(resolve(assetsDirectory, name))
    return {
      name,
      rawBytes: content.byteLength,
      gzipBytes: gzipSync(content).byteLength,
    }
  }),
)
chunks.sort((left, right) => right.rawBytes - left.rawBytes)

const oversized = chunks.filter(
  ({ rawBytes, gzipBytes }) => rawBytes > maxRawBytes || gzipBytes > maxGzipBytes,
)
if (oversized.length > 0) {
  for (const chunk of oversized) {
    console.error(
      `${chunk.name}: ${formatKiB(chunk.rawBytes)} raw / ${formatKiB(chunk.gzipBytes)} gzip ` +
        `(limits ${formatKiB(maxRawBytes)} raw / ${formatKiB(maxGzipBytes)} gzip)`,
    )
  }
  process.exitCode = 1
} else {
  const largest = chunks[0]
  console.log(
    `Bundle budget passed: ${javascriptFiles.length} chunks; largest ${largest.name} ` +
      `${formatKiB(largest.rawBytes)} raw / ${formatKiB(largest.gzipBytes)} gzip`,
  )
}

function parseBudget(name, fallback) {
  const raw = process.env[name]
  if (raw === undefined) return fallback
  const parsed = Number(raw)
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer byte count`)
  }
  return parsed
}

function formatKiB(bytes) {
  return `${(bytes / KIB).toFixed(1)} KiB`
}
