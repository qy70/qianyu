using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;

class Setup {
    [STAThread] static int Main(string[] args) {
        Console.OutputEncoding = Encoding.UTF8;
        string root = AppDomain.CurrentDomain.BaseDirectory;
        if (args.Contains("--install-from")) return UpdateSetup.Run(args, root);
        bool check = args.Contains("--check");
        try {
            if (!Environment.Is64BitOperatingSystem) throw new IOException("需要 Windows 10/11 64 位系统。");
            if (!check) DesktopSupport.AssertNotRunning(root);
            Console.WriteLine("正在准备千鱼，不修改 Windows 脚本策略或安全设置。");
            string python = DesktopSupport.FindPython(root);
            if (python == null && !check) {
                Console.WriteLine("正在下载官方 Python 3.12，请完成随后出现的安装向导。");
                string installer = DesktopSupport.Download("https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe", Path.Combine(root, ".tools", "downloads", "python-3.12.10-amd64.exe"));
                DesktopSupport.RunOfficialInstaller(installer, "Python Software Foundation", root);
                python = DesktopSupport.FindPython(root);
            }
            if (python == null) throw new IOException("未找到 Python 3.12 x64，请完成官方安装后重新运行安装入口。");
            var info = DesktopSupport.Command(python, DesktopSupport.Quote(Path.Combine(root, "scripts", "windows_setup.py")) + (check ? " --check" : ""), root);
            info.CreateNoWindow = false;
            using (var child = Process.Start(info)) { child.WaitForExit(); if (child.ExitCode != 0) throw new IOException("依赖准备未完成，请查看上方错误和 程序\\.runtime\\install.log。"); }
            if (check) return 0;
            if (!args.Contains("--dependencies-only")) {
                bool webview = new[] { Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData) }
                    .Any(folder => Directory.Exists(Path.Combine(folder, "Microsoft", "EdgeWebView", "Application")));
                if (!webview) {
                    Console.WriteLine("正在下载微软官方 WebView2，请完成安装向导。");
                    string installer = DesktopSupport.Download("https://go.microsoft.com/fwlink/p/?LinkId=2124703", Path.Combine(root, ".tools", "downloads", "WebView2Setup.exe"));
                    DesktopSupport.RunOfficialInstaller(installer, "Microsoft Corporation", root);
                }
                DesktopSupport.CreateShortcut(root);
                Console.WriteLine("安装完成，桌面已创建“千鱼”。");
                if (!args.Contains("--no-open")) Process.Start(new ProcessStartInfo(Path.Combine(root, "千鱼.exe")) { WorkingDirectory = root, UseShellExecute = true });
            }
            return 0;
        } catch (Exception e) {
            Console.Error.WriteLine("安装尚未完成：" + e.Message);
            if (!check && !Console.IsInputRedirected) { Console.WriteLine("请保留以上错误信息。按回车关闭。"); Console.ReadLine(); }
            return 1;
        }
    }
}
