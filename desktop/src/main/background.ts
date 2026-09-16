import { app, BrowserWindow, dialog, nativeImage } from 'electron'
import fs from 'node:fs/promises'
import path from 'node:path'

const destination = () => path.join(app.getPath('userData'), 'appearance', 'background.jpg')
export async function getBackground(): Promise<string | null> {
  try {
    return `data:image/jpeg;base64,${(await fs.readFile(destination())).toString('base64')}`
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return null
    throw error
  }
}
export async function chooseBackground(window: BrowserWindow): Promise<string | null> {
  const selected = await dialog.showOpenDialog(window, {
    title: '选择背景图片',
    properties: ['openFile'],
    filters: [{ name: '图片', extensions: ['jpg', 'jpeg', 'png'] }]
  })
  if (selected.canceled || !selected.filePaths[0]) return null
  const source = selected.filePaths[0]
  if (!['.jpg', '.jpeg', '.png'].includes(path.extname(source).toLowerCase()))
    throw new Error('请选择 JPG 或 PNG 图片')
  const stat = await fs.stat(source)
  if (!stat.isFile() || stat.size > 20 * 1024 * 1024) throw new Error('图片大小不能超过 20 MB')
  let bitmap = nativeImage.createFromBuffer(await fs.readFile(source))
  if (bitmap.isEmpty()) throw new Error('无法读取这张图片，请选择有效的 JPG 或 PNG 文件')
  const size = bitmap.getSize()
  if (size.width * size.height > 50_000_000)
    throw new Error('图片尺寸过大，请选择不超过 5000 万像素的图片')
  if (Math.max(size.width, size.height) > 2560)
    bitmap = bitmap.resize(
      size.width >= size.height
        ? { width: 2560, quality: 'good' }
        : { height: 2560, quality: 'good' }
    )
  const bytes = bitmap.toJPEG(85)
  const dest = destination()
  await fs.mkdir(path.dirname(dest), { recursive: true })
  await fs.writeFile(dest + '.tmp', bytes)
  await fs.rename(dest + '.tmp', dest)
  return `data:image/jpeg;base64,${bytes.toString('base64')}`
}
export async function clearBackground(): Promise<void> {
  await fs.unlink(destination()).catch((error) => {
    if (error.code !== 'ENOENT') throw error
  })
}
