using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Win32;

internal static class Program
{
    private const string PatchVersion = "0.6.7";
    private const string RunKey = @"Software\Microsoft\Windows\CurrentVersion\Run";
    private const string RunValueName = "Poe2PricePatch";
    private static Mutex? UiMutex;

    [DllImport("user32.dll")] private static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] private static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);

    [STAThread]
    public static int Main(string[] args)
    {
        ApplicationConfiguration.Initialize();
        return args.Any(a => string.Equals(a, "--background", StringComparison.OrdinalIgnoreCase))
            ? RunBackground() : MainInteractive(args);
    }

    private static int MainInteractive(string[] args)
    {
        UiMutex = new Mutex(false, "Local\\Poe2PricePatch-InteractiveUI");
        if (!TryTakeInstanceMutex(UiMutex))
        {
            ActivateExistingUi();
            UiMutex.Dispose(); UiMutex = null;
            return 0;
        }
        try
        {
            var mode = "select";
            var scriptArgs = args;
            if (args.Length > 0 && TryParseMode(args[0], out var explicitMode))
            {
                mode = explicitMode; scriptArgs = args.Skip(1).ToArray();
            }
            var appDir = Path.TrimEndingDirectorySeparator(Path.GetFullPath(AppContext.BaseDirectory));
            var scriptPath = Path.Combine(appDir, "tools", "price_patch_gui.ps1");
            if (!File.Exists(scriptPath)) throw new FileNotFoundException("发布目录缺少 tools\\price_patch_gui.ps1，请完整解压发布包。", scriptPath);
            var startInfo = CreatePowerShellStartInfo(appDir, scriptPath);
            startInfo.ArgumentList.Add("-Mode"); startInfo.ArgumentList.Add(mode);
            foreach (var value in scriptArgs) startInfo.ArgumentList.Add(value);
            SetPatchEnvironment(startInfo, appDir);
            using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("无法启动 PowerShell 图形界面。");
            process.WaitForExit();
            return process.ExitCode;
        }
        catch (Exception ex)
        {
            WriteLauncherLog("GUI startup failed: " + ex);
            MessageBox.Show(ex.Message, $"POE 物价补丁 v{PatchVersion}", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
        finally { UiMutex?.Dispose(); UiMutex = null; }
    }

    private static int RunBackground()
    {
        try
        {
            var appDir = Path.TrimEndingDirectorySeparator(Path.GetFullPath(AppContext.BaseDirectory));
            var toolsDir = Path.Combine(appDir, "tools");
            if (!File.Exists(Path.Combine(toolsDir, "auto_update_worker.ps1"))) throw new FileNotFoundException("发布目录缺少 tools\\auto_update_worker.ps1，请完整解压发布包。");
            using var context = new TrayContext(appDir, toolsDir);
            Application.Run(context);
            return 0;
        }
        catch (Exception ex)
        {
            WriteLauncherLog("Tray startup failed: " + ex);
            MessageBox.Show(ex.Message, $"POE 物价补丁 v{PatchVersion}", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private sealed class TrayContext : ApplicationContext
    {
        private readonly string appDir, toolsDir, settingsPath;
        private readonly NotifyIcon icon;
        private readonly System.Threading.Timer timer;
        private readonly Mutex backgroundMutex;
        private readonly ToolStripMenuItem autoStartItem, autoUpdateItem;
        private int running;
        private string lastMessage = "尚未执行自动更新";

        public TrayContext(string appDir, string toolsDir)
        {
            this.appDir = appDir; this.toolsDir = toolsDir;
            backgroundMutex = new Mutex(false, "Local\\Poe2PricePatch-Background");
            if (!TryTakeInstanceMutex(backgroundMutex)) { backgroundMutex.Dispose(); throw new InvalidOperationException("后台托盘实例已在运行。"); }
            settingsPath = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PoePricePatch", "settings.json");
            RepairAutoStartRegistration();
            var menu = new ContextMenuStrip();
            menu.Items.Add("打开主界面", null, (_, _) => OpenUi());
            menu.Items.Add("立即更新", null, (_, _) => _ = Task.Run(RunWorker));
            menu.Items.Add("查看最近结果", null, (_, _) => MessageBox.Show(lastMessage, "POE 物价补丁"));
            menu.Items.Add(new ToolStripSeparator());
            autoStartItem = new ToolStripMenuItem("开机自动启动"); autoStartItem.Click += (_, _) => ToggleAutoStart(); menu.Items.Add(autoStartItem);
            autoUpdateItem = new ToolStripMenuItem("每小时自动更新物价"); autoUpdateItem.Click += (_, _) => ToggleAutoUpdate(); menu.Items.Add(autoUpdateItem);
            menu.Items.Add(new ToolStripSeparator()); menu.Items.Add("退出程序", null, (_, _) => ExitThread());
            icon = new NotifyIcon { Text = "POE 物价补丁", Icon = SystemIcons.Application, Visible = true, ContextMenuStrip = menu };
            icon.DoubleClick += (_, _) => OpenUi();
            RefreshState();
            timer = new System.Threading.Timer(_ => Tick(), null, TimeSpan.FromMinutes(1), TimeSpan.FromHours(1));
            if (ReadBool("auto_update") && HasConfirmedSelection()) _ = Task.Run(RunWorker);
        }

        private Dictionary<string, JsonElement> ReadState()
        {
            try { return File.Exists(settingsPath) ? JsonSerializer.Deserialize<Dictionary<string, JsonElement>>(File.ReadAllText(settingsPath)) ?? new() : new(); }
            catch (Exception ex) { WriteLauncherLog("Unable to read settings: " + ex.Message); return new(); }
        }
        private bool ReadBool(string key) => ReadState().TryGetValue(key, out var value) && value.ValueKind == JsonValueKind.True;
        private bool HasConfirmedSelection() => ReadState().TryGetValue("last_selection", out var value) && value.ValueKind == JsonValueKind.Object && value.TryGetProperty("confirmed", out var confirmed) && confirmed.ValueKind == JsonValueKind.True;
        private void RefreshState()
        {
            autoStartItem.Checked = IsAutoStartRegistered(); autoUpdateItem.Checked = ReadBool("auto_update");
            var state = ReadState();
            if (state.TryGetValue("last_auto_update_message", out var message) && message.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(message.GetString())) lastMessage = message.GetString()!;
        }
        private void OpenUi() { try { Process.Start(new ProcessStartInfo(Environment.ProcessPath!) { UseShellExecute = true }); } catch (Exception ex) { WriteLauncherLog("Unable to open GUI: " + ex); } }
        private void ToggleAutoStart() { var enabled = !IsAutoStartRegistered(); SetAutoStartRegistration(enabled); UpdateState("auto_start", enabled); RefreshState(); }
        private void ToggleAutoUpdate()
        {
            var enabled = !ReadBool("auto_update");
            if (enabled && !HasConfirmedSelection()) { MessageBox.Show("请先完成一次手动更新物价，后台更新才知道游戏路径和服务器。", "POE 物价补丁"); return; }
            UpdateState("auto_update", enabled); RefreshState(); if (enabled) _ = Task.Run(RunWorker);
        }
        private void UpdateState(string key, bool value)
        {
            try
            {
                var state = ReadState().ToDictionary(pair => pair.Key, pair => pair.Value);
                state[key] = JsonSerializer.SerializeToElement(value); state["version"] = JsonSerializer.SerializeToElement(2); state["saved_at_utc"] = JsonSerializer.SerializeToElement(DateTime.UtcNow.ToString("O"));
                var directory = Path.GetDirectoryName(settingsPath)!; Directory.CreateDirectory(directory);
                var temp = Path.Combine(directory, ".settings-" + Guid.NewGuid().ToString("N") + ".tmp");
                File.WriteAllText(temp, JsonSerializer.Serialize(state, new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
                try { File.Move(temp, settingsPath, true); } finally { if (File.Exists(temp)) File.Delete(temp); }
            } catch (Exception ex) { WriteLauncherLog("Unable to update settings: " + ex); }
        }
        private bool IsAutoStartRegistered()
        {
            try { using var key = Registry.CurrentUser.OpenSubKey(RunKey, false); var value = key?.GetValue(RunValueName)?.ToString(); return !string.IsNullOrWhiteSpace(value) && value.Contains(Environment.ProcessPath ?? "", StringComparison.OrdinalIgnoreCase) && value.Contains("--background", StringComparison.OrdinalIgnoreCase); } catch { return false; }
        }
        private void SetAutoStartRegistration(bool enabled)
        {
            try { using var key = Registry.CurrentUser.CreateSubKey(RunKey); if (enabled) key?.SetValue(RunValueName, $"\"{Environment.ProcessPath}\" --background"); else key?.DeleteValue(RunValueName, false); } catch (Exception ex) { WriteLauncherLog("Unable to set auto start: " + ex); }
        }
        private void RepairAutoStartRegistration() { SetAutoStartRegistration(ReadBool("auto_start")); }
        private void Tick() { if (ReadBool("auto_update") && HasConfirmedSelection()) _ = Task.Run(RunWorker); }
        private void RunWorker()
        {
            if (Interlocked.Exchange(ref running, 1) != 0) return;
            try
            {
                var script = Path.Combine(toolsDir, "auto_update_worker.ps1");
                var startInfo = CreatePowerShellStartInfo(appDir, script); startInfo.ArgumentList.Add("-Background"); SetPatchEnvironment(startInfo, appDir);
                using var process = Process.Start(startInfo) ?? throw new InvalidOperationException("无法启动自动更新 Worker。");
                if (!process.WaitForExit(3_600_000)) { try { process.Kill(true); } catch { } lastMessage = "自动更新超时，已终止后台进程"; ShowFailure(lastMessage); return; }
                RefreshState();
                if (process.ExitCode != 0) { lastMessage = "自动更新失败，退出码：" + process.ExitCode + "。" + lastMessage; ShowFailure(lastMessage); }
            }
            catch (Exception ex) { lastMessage = "自动更新失败：" + ex.Message; WriteLauncherLog(lastMessage); ShowFailure(lastMessage); }
            finally { Volatile.Write(ref running, 0); }
        }
        private void ShowFailure(string message) => icon.ShowBalloonTip(5000, "POE 物价补丁", message, ToolTipIcon.Warning);
        protected override void Dispose(bool disposing)
        {
            if (disposing) { timer.Dispose(); icon.Visible = false; icon.Dispose(); try { backgroundMutex.ReleaseMutex(); } catch { } backgroundMutex.Dispose(); }
            base.Dispose(disposing);
        }
    }

    private static ProcessStartInfo CreatePowerShellStartInfo(string appDir, string scriptPath)
    {
        var info = new ProcessStartInfo { FileName = "powershell.exe", UseShellExecute = false, CreateNoWindow = true, WindowStyle = ProcessWindowStyle.Hidden, WorkingDirectory = appDir };
        foreach (var arg in new[] { "-NoProfile", "-STA", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", scriptPath }) info.ArgumentList.Add(arg);
        return info;
    }
    private static void SetPatchEnvironment(ProcessStartInfo info, string appDir) { info.Environment["POE2_PATCH_ROOT"] = appDir; info.Environment["POE2_PATCH_RELEASE"] = "1"; info.Environment["POE2_PATCH_LAUNCHER"] = Environment.ProcessPath ?? ""; }
    private static void ActivateExistingUi()
    {
        try { var current = Environment.ProcessId; foreach (var process in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(Environment.ProcessPath))) { try { if (process.Id == current || process.MainWindowHandle == IntPtr.Zero) continue; ShowWindowAsync(process.MainWindowHandle, 9); SetForegroundWindow(process.MainWindowHandle); break; } finally { process.Dispose(); } } } catch { }
    }
    private static string? ResolveMutexScopeRoot(string patchRoot, string[] scriptArgs)
    {
        for (var i = 0; i + 1 < scriptArgs.Length; i++)
            if ((string.Equals(scriptArgs[i], "-Poe1Dir", StringComparison.OrdinalIgnoreCase) || string.Equals(scriptArgs[i], "-Poe2Dir", StringComparison.OrdinalIgnoreCase)) && !string.IsNullOrWhiteSpace(scriptArgs[i + 1]))
                return Path.GetFullPath(scriptArgs[i + 1], patchRoot);
        var patchParent = Directory.GetParent(patchRoot)?.FullName;
        if (!string.IsNullOrWhiteSpace(patchParent) && IsPoe2GameDirectory(patchParent)) return patchParent;
        return TryReadSavedGameDirectory();
    }
    private static bool IsPoe2GameDirectory(string path) => Directory.Exists(path) && (File.Exists(Path.Combine(path, "Content.ggpk")) || File.Exists(Path.Combine(path, "Bundles2", "_.index.bin")));
    private static string? TryReadSavedGameDirectory()
    {
        try { foreach (var path in new[] { Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PoePricePatch", "settings.json"), Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Poe2PricePatch", "settings.json") }) { if (!File.Exists(path)) continue; using var settings = JsonDocument.Parse(File.ReadAllText(path)); foreach (var property in new[] { "poe2_game_directory", "poe1_game_directory", "game_directory" }) if (settings.RootElement.TryGetProperty(property, out var value) && value.ValueKind == JsonValueKind.String && !string.IsNullOrWhiteSpace(value.GetString())) return Path.TrimEndingDirectorySeparator(Path.GetFullPath(value.GetString()!)); } } catch { } return null;
    }
    private static string CreateInstanceMutexName(string gameDirectory) { var normalized = Path.TrimEndingDirectorySeparator(Path.GetFullPath(gameDirectory)).ToUpperInvariant(); return "Local\\Poe2PricePatch-Launcher-Game-" + Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(normalized))); }
    private static bool TryTakeInstanceMutex(Mutex mutex) { try { return mutex.WaitOne(0); } catch (AbandonedMutexException) { return true; } }
    private static bool TryParseMode(string value, out string mode) { mode = value.Trim().ToLowerInvariant(); return mode is "select" or "update" or "restore"; }
    private static void WriteLauncherLog(string message) { try { var dir = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "PoePricePatch", "logs"); Directory.CreateDirectory(dir); File.AppendAllText(Path.Combine(dir, "launcher.log"), DateTime.UtcNow.ToString("O") + " " + message + Environment.NewLine, new UTF8Encoding(false)); } catch { } }
}
