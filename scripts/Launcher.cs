using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Windows.Forms;

class Launcher {
    [STAThread] static int Main(string[] args) {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        try {
            if (DesktopSupport.TryFocus(root)) return 0;
            string python = DesktopSupport.FindPython(root);
            if (python == null || !Directory.Exists(Path.Combine(root, ".runtime", "site-packages", "webview")))
                throw new IOException("请先运行“安装千鱼.cmd”完成安装。");
            string runtime = Path.Combine(root, ".runtime");
            Directory.CreateDirectory(runtime);
            var start = DesktopSupport.Command(python, "-m fatfish.desktop"
                + (Array.IndexOf(args, "--no-qq") >= 0 ? " --no-qq" : "")
                + (Array.IndexOf(args, "--resume-core") >= 0 ? " --resume-core" : ""), root);
            start.EnvironmentVariables["PYTHONPATH"] = Path.Combine(runtime, "site-packages") + ";" + Path.Combine(root, "engine", "MaiBot") + ";" + root;
            start.EnvironmentVariables["PYTHONUTF8"] = "1";
            start.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            string errorPath = Path.Combine(runtime, "manager.err.log");
            using (var output = new StreamWriter(Path.Combine(runtime, "manager.out.log"), false, Encoding.UTF8))
            using (var error = new StreamWriter(errorPath, false, Encoding.UTF8))
            using (var process = new Process { StartInfo = start }) {
                output.AutoFlush = true; error.AutoFlush = true;
                process.OutputDataReceived += (s, e) => { if (e.Data != null) output.WriteLine(e.Data); };
                process.ErrorDataReceived += (s, e) => { if (e.Data != null) error.WriteLine(e.Data); };
                process.Start();
                File.WriteAllText(Path.Combine(runtime, "manager.pid"), process.Id.ToString());
                process.BeginOutputReadLine(); process.BeginErrorReadLine();
                process.WaitForExit();
                if (process.ExitCode != 0) throw new IOException("千鱼未能启动，请将以下日志提供给维护者：\n" + errorPath);
            }
            return 0;
        } catch (Exception e) { MessageBox.Show(e.Message, "千鱼启动未完成", MessageBoxButtons.OK, MessageBoxIcon.Warning); return 1; }
    }
}
