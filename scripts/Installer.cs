using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Text;
using System.Windows.Forms;

class Installer {
    static string ChooseTarget() {
        string home = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Fatfish");
        string location = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Fatfish-installation.json");
        if (File.Exists(location)) {
            var last = DesktopSupport.Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(location, Encoding.UTF8));
            if (last.ContainsKey("home") && Directory.Exists((string)last["home"])) home = (string)last["home"];
        }
        using (var form = new Form()) {
            form.Text = "安装 / 升级千鱼 " + BuildInfo.Version;
            form.ClientSize = new Size(560, 230);
            form.StartPosition = FormStartPosition.CenterScreen;
            form.FormBorderStyle = FormBorderStyle.FixedDialog;
            form.MaximizeBox = false; form.MinimizeBox = false;
            var description = new Label { Text = "已有旧版：选择原安装文件夹，程序会先备份再自动升级。\n记忆、知识、账号和自定义内容保留；只移除识别出的旧预置模板。\n全新安装：不预设人格或说话风格。", Left = 18, Top = 18, Width = 520, Height = 68 };
            var path = new TextBox { Text = home, Left = 18, Top = 95, Width = 420, ReadOnly = true };
            var browse = new Button { Text = "选择目录", Left = 448, Top = 93, Width = 92 };
            browse.Click += (s, e) => { using (var dialog = new FolderBrowserDialog { SelectedPath = path.Text, Description = "选择原安装目录；首次安装请选择空文件夹" }) if (dialog.ShowDialog(form) == DialogResult.OK) path.Text = dialog.SelectedPath; };
            var note = new Label { Text = "首次准备依赖需要联网。安装不会修改系统安全策略。", Left = 18, Top = 135, Width = 520, Height = 26 };
            var ok = new Button { Text = "安装 / 升级", Left = 322, Top = 180, Width = 120, DialogResult = DialogResult.OK };
            var cancel = new Button { Text = "取消", Left = 450, Top = 180, Width = 90, DialogResult = DialogResult.Cancel };
            form.Controls.AddRange(new Control[] { description, path, browse, note, ok, cancel });
            form.AcceptButton = ok; form.CancelButton = cancel;
            if (form.ShowDialog() != DialogResult.OK) return null;
            home = Path.GetFullPath(path.Text).TrimEnd(Path.DirectorySeparatorChar);
            if (home.StartsWith("\\\\", StringComparison.Ordinal) || home.Length <= 3) throw new IOException("请选择本机独立文件夹，不能选择磁盘根目录或网络共享。");
            return home;
        }
    }
    internal static void Extract(string root) {
        root = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar);
        const string prefix = "千鱼纯净版/";
        using (var payload = Assembly.GetExecutingAssembly().GetManifestResourceStream("payload.zip"))
        using (var archive = new ZipArchive(payload, ZipArchiveMode.Read)) {
            var manifestEntry = archive.GetEntry(prefix + "release-manifest.json");
            if (manifestEntry == null) throw new InvalidDataException("安装包缺少文件清单。");
            Dictionary<string, object> manifest;
            using (var reader = new StreamReader(manifestEntry.Open(), Encoding.UTF8)) manifest = DesktopSupport.Json.Deserialize<Dictionary<string, object>>(reader.ReadToEnd());
            if (!Object.Equals(manifest["personal_data"], false) || (string)manifest["version"] != BuildInfo.Version) throw new InvalidDataException("安装包版本或纯净标记不正确。");
            var files = (Dictionary<string, object>)manifest["files"];
            if (archive.Entries.Count != files.Count + 1) throw new InvalidDataException("安装包清单不完整。");
            var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            // Check every path and hash before writing any payload file.
            foreach (var entry in archive.Entries) {
                if (!entry.FullName.StartsWith(prefix, StringComparison.Ordinal)) throw new InvalidDataException("安装包目录无效。");
                string relative = entry.FullName.Substring(prefix.Length);
                string target = Path.GetFullPath(Path.Combine(root, relative));
                DesktopSupport.AssertNoDirectoryLinks(root, target);
                if (relative.Contains("\\") || !seen.Add(target) || !target.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("安装包路径无效。");
                foreach (string segment in relative.Split('/'))
                    if (segment == ".." || segment == "instances" || segment == ".runtime" || segment == ".tools" || segment == "backups") throw new InvalidDataException("安装包包含非程序目录。");
                if (entry == manifestEntry) continue;
                using (var content = entry.Open())
                    if (!files.ContainsKey(relative) || DesktopSupport.Digest(content) != (string)files[relative]) throw new InvalidDataException("安装包文件校验失败：" + relative);
            }
            foreach (var entry in archive.Entries) {
                string target = Path.GetFullPath(Path.Combine(root, entry.FullName.Substring(prefix.Length)));
                Directory.CreateDirectory(Path.GetDirectoryName(target));
                using (var input = entry.Open()) using (var output = File.Create(target)) input.CopyTo(output);
            }
        }
    }
    [STAThread] static int Main(string[] args) {
        bool extractOnly = args.Length == 2 && args[0] == "--extract-only";
        string stage = null;
        string stageBase = Path.GetFullPath(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Fatfish-install-staging"));
        try {
            if (extractOnly) { Extract(args[1]); return 0; }
            string home = ChooseTarget();
            if (home == null) return 0;
            stage = Path.Combine(stageBase, Guid.NewGuid().ToString("N"));
            Extract(stage);
            var start = new ProcessStartInfo(Path.Combine(stage, "程序", "千鱼安装助手.exe"), "--install-from " + DesktopSupport.Quote(stage) + " --target " + DesktopSupport.Quote(home)) { WorkingDirectory = stage, UseShellExecute = true, WindowStyle = ProcessWindowStyle.Normal };
            using (var child = Process.Start(start)) { child.WaitForExit(); return child.ExitCode; }
        } catch (Exception e) {
            if (extractOnly) Console.Error.WriteLine(e.Message);
            else MessageBox.Show(e.Message, "千鱼安装未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning);
            return 1;
        } finally {
            if (stage != null && Directory.Exists(stage)) {
                string resolved = Path.GetFullPath(stage);
                if (resolved.StartsWith(stageBase + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase)
                    && (File.GetAttributes(resolved) & FileAttributes.ReparsePoint) == 0) {
                    try { Directory.Delete(resolved, true); } catch (IOException) { }
                }
            }
        }
    }
}
