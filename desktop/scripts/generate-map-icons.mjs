import { createRequire } from 'node:module'
import fs from 'node:fs/promises'
const require = createRequire(import.meta.url)
const collection = require('@iconify-json/ph/icons.json')
const names = [
  'map-trifold',
  'path',
  'plus',
  'minus',
  'corners-out',
  'crosshair',
  'trash',
  'github-logo'
]
const icons = Object.fromEntries(
  names.map((name) => [`ph:${name}`, { ...collection.icons[name], width: 256, height: 256 }])
)
await fs.writeFile(
  new URL('../src/renderer/map-icons.ts', import.meta.url),
  '// Generated from @iconify-json/ph by scripts/generate-map-icons.mjs.\nexport const mapIcons = ' +
    JSON.stringify(icons, null, 2) +
    '\n'
)
