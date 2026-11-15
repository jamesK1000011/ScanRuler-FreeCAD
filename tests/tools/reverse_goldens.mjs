// Ported from ScanRuler by CNC Kitchen (Stefan Hermann): plugins/reverse/tests/reKit.ts (build), plugins/reverse/core/build.ts (what a build hands back)
// SPDX-License-Identifier: AGPL-3.0-only
//
// The parity goldens: every fixture of tests/reverse_fixtures/kernel_builds.json
// built by the ORIGINAL engine — ScanRuler's own resolveFeatures and Builder
// on occt-wasm — and what came out written to
// tests/reverse_fixtures/kernel_goldens.json, which test_reverse_parity.py
// holds the FreeCAD port to. Run it where a ScanRuler checkout has its
// packages installed (npm ci: occt-wasm 5.15.0), under Node 22 or later:
//
//   node --experimental-transform-types tests/tools/reverse_goldens.mjs <ScanRuler checkout>
//
// Nothing is written by hand: a golden is what the original's builder said.
// It loads the TypeScript as it stands (type stripping), resolving the
// extensionless imports the app's bundler resolves.

import { register } from 'node:module'
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const LOADER = `
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
export async function resolve(spec, ctx, next) {
  if ((spec.startsWith('.') || spec.startsWith('/')) && !/\\.[cm]?[jt]sx?$/.test(spec) && !/\\.json$/.test(spec)) {
    const base = new URL(spec, ctx.parentURL)
    for (const ext of ['.ts', '.tsx', '/index.ts']) {
      const u = new URL(base.href + ext)
      if (existsSync(fileURLToPath(u))) return next(u.href, ctx)
    }
  }
  return next(spec, ctx)
}`
register(`data:text/javascript,${encodeURIComponent(LOADER)}`, import.meta.url)

const here = dirname(fileURLToPath(import.meta.url))
const repo = resolve(here, '..', '..')
const upstream = process.argv[2]
if (!upstream) {
  console.error('usage: node --experimental-transform-types tests/tools/reverse_goldens.mjs <ScanRuler checkout>')
  process.exit(2)
}
const core = (m) => pathToFileURL(join(resolve(upstream), 'plugins', 'reverse', 'core', m)).href

const { Builder } = await import(core('build.ts'))
const { ReKernel } = await import(core('kernel.ts'))
const { findRegions } = await import(core('regions.ts'))
const { resolveFeatures } = await import(core('resolve.ts'))
const { applyParameters, evaluateParameters } = await import(core('parameters.ts'))

const fixtures = JSON.parse(readFileSync(join(repo, 'tests', 'reverse_fixtures', 'kernel_builds.json'), 'utf8')).fixtures
const kernel = await ReKernel.load()
const ctx = { sections: [], elements: [], modelCenter: [0, 0, 0] }

const out = []
for (const fx of fixtures) {
  let features = fx.features
  if (fx.parameters) features = applyParameters(features, evaluateParameters(fx.parameters).scope).features
  const steps = resolveFeatures(features, ctx, (f) => findRegions(f.sketch))
  const sketches = new Map(features.filter((f) => f.kind === 'sketch').map((f) => [f.id, f.sketch]))
  const builder = new Builder(kernel)
  const r = builder.build(steps, (id) => sketches.get(id))
  out.push({
    name: fx.name,
    results: r.results.map((x) => ({ id: x.id, status: x.status, ...(x.message ? { message: x.message } : {}), ...(x.warning ? { warning: x.warning } : {}), ...(x.note ? { note: x.note } : {}), ...(x.bodies ? { bodies: x.bodies } : {}) })),
    bodies: r.bodies.map((b) => {
      const shape = builder.body(b.id)
      const origins = {}
      for (const f of b.topology.faces) origins[f.fingerprint.origin] = (origins[f.fingerprint.origin] ?? 0) + 1
      return {
        id: b.id,
        name: b.name,
        surface: b.surface,
        closed: b.closed,
        volume: b.volume,
        area: shape === undefined ? null : kernel.surfaceArea(shape),
        box: b.box,
        faces: b.faces,
        edges: b.topology.edges.length,
        faceKinds: b.topology.faces.map((f) => f.fingerprint.kind).sort(),
        origins,
      }
    }),
  })
  builder.dispose()
}

const target = join(repo, 'tests', 'reverse_fixtures', 'kernel_goldens.json')
writeFileSync(target, `${JSON.stringify({ about: `Built by ScanRuler's own engine (${kernel.version}), tests/tools/reverse_goldens.mjs`, goldens: out }, null, 1)}\n`)
console.log(`${out.length} goldens written to ${target}`)
