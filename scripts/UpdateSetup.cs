using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

internal static class UpdateSetup {
    static string Option(string[] args, string name) {
        int index = Array.IndexOf(args, name);
        if (index < 0 || index + 1 >= args.Length) throw new IOException("安装参数不完整。");
        return args[index + 1];
    }
    internal static int Run(string[] args, string sourceRoot) {
        Console.OutputEncoding = Encoding.UTF8;
        try {
            string from = Path.GetFullPath(Option(args, "--install-from"));
            string target = Path.GetFullPath(Option(args, "--target"));
            string oldProgram = File.Exists(Path.Combine(target, "程序", "fatfish", "core.py")) ? Path.Combine(target, "程序") : target;
            string python = DesktopSupport.FindPython(Directory.Exists(oldProgram) ? oldProgram : sourceRoot);
            if (python == null) {
                Console.WriteLine("正在下载官方 Python 3.12，请完成安装向导。");
                string installer = DesktopSupport.Download("https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe", Path.Combine(sourceRoot, ".tools", "downloads", "python-3.12.10-amd64.exe"));
                DesktopSupport.RunOfficialInstaller(installer, "Python Software Foundation", sourceRoot);
                python = DesktopSupport.FindPython(sourceRoot);
            }
            if (python == null) throw new IOException("Python 3.12 x64 尚未安装完成。");
            bool webview = new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) }
                .Any(folder => Directory.Exists(Path.Combine(folder, "Microsoft", "EdgeWebView", "Application")));
            if (!webview) {
                Console.WriteLine("正在准备微软官方 WebView2，请完成安装向导。");
                string installer = DesktopSupport.Download("https://go.microsoft.com/fwlink/p/?LinkId=2124703", Path.Combine(sourceRoot, ".tools", "downloads", "WebView2Setup.exe"));
                DesktopSupport.RunOfficialInstaller(installer, "Microsoft Corporation", sourceRoot);
            }
            string resultFile = Path.Combine(from, "upgrade-result.json");
            var info = DesktopSupport.Command(python, "-I " + DesktopSupport.Quote(Path.Combine(sourceRoot, "scripts", "install_or_upgrade.py")) + " --source " + DesktopSupport.Quote(from) + " --target " + DesktopSupport.Quote(target) + " --result " + DesktopSupport.Quote(resultFile), sourceRoot);
            info.CreateNoWindow = false;
            info.EnvironmentVariables.Remove("PYTHONPATH");
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            using (var child = Process.Start(info)) {
                child.WaitForExit();
                if (child.ExitCode != 0) throw new IOException("安装/升级未完成，请查看上方错误；已开始的事务会恢复，备份会保留。");
            }
            var result = DesktopSupport.Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(resultFile, Encoding.UTF8));
            string root = (string)result["program_root"];
            DesktopSupport.CreateShortcut(root);
            File.WriteAllText(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Fatfish-installation.json"), DesktopSupport.Json.Serialize(new Dictionary<string, object> { { "home", target } }), Encoding.UTF8);
            Console.WriteLine("安装/升级完成。桌面已创建“千鱼”，记忆、知识和自定义资料已保留。");
            bool resume = Object.Equals(result["resume_core"], true);
            if (!args.Contains("--no-open")) Process.Start(new ProcessStartInfo(Path.Combine(root, "千鱼.exe"), resume ? "--resume-core" : "") { WorkingDirectory = root, UseShellExecute = true });
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine("安装/升级尚未完成：" + error.Message);
            if (!Console.IsInputRedirected) { Console.WriteLine("请保留以上信息。按回车关闭。"); Console.ReadLine(); }
            return 1;
        }
    }
}
