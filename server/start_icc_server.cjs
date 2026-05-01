const { spawn, spawnSync } = require('node:child_process')
const path = require('node:path')

const root = path.resolve(__dirname, '..')
const server = path.join(root, 'server', 'icc_convert_server.py')
const userProfile = process.env.USERPROFILE || process.env.HOME || ''
const candidates = [
  process.env.PYTHON,
  'python',
  path.join(userProfile, '.cache', 'codex-runtimes', 'codex-primary-runtime', 'dependencies', 'python', 'python.exe'),
].filter(Boolean)

function hasImageCms(python) {
  const result = spawnSync(
    python,
    ['-c', 'from PIL import ImageCms'],
    { stdio: 'ignore' }
  )
  return result.status === 0
}

const python = candidates.find(hasImageCms)
if (!python) {
  console.error('No Python environment with Pillow ImageCms was found.')
  console.error('Install Pillow, or set PYTHON to a Python executable that can import PIL.ImageCms.')
  process.exit(1)
}

const child = spawn(python, [server], {
  cwd: root,
  stdio: 'inherit',
  env: process.env,
})

child.on('exit', code => process.exit(code || 0))
