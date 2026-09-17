interface LoginApi {
  getLoginItemSettings(options: { path: string; args: string[] }): {
    openAtLogin: boolean
    executableWillLaunchAtLogin: boolean
    launchItems?: { path: string; args: string[]; enabled: boolean }[]
  }
  setLoginItemSettings(options: { openAtLogin: boolean; path: string; args: string[] }): void
}

// Read back the exact executable AND arguments. StartupApproved can disable an existing Run key.
export function reconcileAutoStart(api: LoginApi, executable: string, wanted: boolean): string {
  const options = { path: executable, args: ['--hidden'] }
  let actual = api.getLoginItemSettings(options)
  // Deleting uses the application's registry value name, even when it still points
  // to a previous portable location that getLoginItemSettings no longer matches.
  if (!wanted || !actual.openAtLogin) {
    api.setLoginItemSettings({ ...options, openAtLogin: wanted })
    actual = api.getLoginItemSettings(options)
  }
  if (wanted && !actual.openAtLogin)
    throw new Error('开机启动项未成功保存，请检查 Windows 启动应用设置')
  if (!wanted && actual.openAtLogin)
    throw new Error('开机启动项未成功关闭，请检查 Windows 启动应用设置')
  const matching = actual.launchItems?.filter(
    (item) =>
      item.path.toLowerCase() === executable.toLowerCase() &&
      item.args.length === 1 &&
      item.args[0] === '--hidden'
  )
  const enabled = matching?.length
    ? matching.some((item) => item.enabled)
    : actual.executableWillLaunchAtLogin
  if (wanted && !enabled) return '已被 Windows 禁用，请在任务管理器 → 启动应用中启用物价补丁。'
  return wanted ? '已核对启动项，登录 Windows 后在托盘中启动。' : '开机自动启动已关闭。'
}

export function shouldShowSecondInstance(argv: string[] = []): boolean {
  return !argv.includes('--hidden')
}
