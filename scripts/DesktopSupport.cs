using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Net;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;

// Native bootstrap: never changes script policy, application control or trust stores.
internal static class DesktopSupport {
    internal static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
    internal static string Quote(string text) { return "\"" + text.Replace("\"", "\\\"") + "\""; }
    internal static ProcessStartInfo Command(string file, string args, string root) {
        return new ProcessStartInfo(file, args) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
    }
    internal static string Capture(string file, string args, string root) {
        var info = Command(file, args, root);
        info.RedirectStandardOutput = true; info.RedirectStandardError = true;
        using (var p = Process.Start(info)) {
            if (!p.WaitForExit(15000)) { p.Kill(); throw new IOException("运行环境检查超时。"); }
            string output = p.StandardOutput.ReadToEnd(), error = p.StandardError.ReadToEnd();
            if (p.ExitCode != 0) throw new IOException(error);
            return output.Trim();
        }
    }
    internal static bool ValidPython(string file, string root) {
        if (String.IsNullOrEmpty(file) || !File.Exists(file)) return false;
        try { return Capture(file, "-I -c \"import sys,struct; assert sys.version_info[:2]==(3,12) and struct.calcsize('P')==8; print('OK')\"", root) == "OK"; }
        catch (System.ComponentModel.Win32Exception e) {
            if (e.NativeErrorCode == 577 || e.NativeErrorCode == 1260 || e.NativeErrorCode == 4551) throw;
            return false;
        } catch (IOException) { return false; }
    }
    internal static string FindPython(string root) {
        var candidates = new List<string>();
        string config = Path.Combine(root, ".runtime", "local.json");
        if (File.Exists(config)) {
            var data = Json.Deserialize<Dictionary<string, object>>(File.ReadAllText(config, Encoding.UTF8));
            if (data.ContainsKey("python")) candidates.Add(Convert.ToString(data["python"]));
        }
        candidates.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python", "Python312", "python.exe"));
        candidates.Add(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Python312", "python.exe"));
        foreach (string candidate in candidates) if (ValidPython(candidate, root)) return candidate;
        foreach (string folder in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';')) {
            if (String.IsNullOrWhiteSpace(folder)) continue;
            string path;
            try { path = Path.GetFullPath(folder.Trim('"')); } catch (ArgumentException) { continue; }
            if (path.EndsWith("Microsoft\\WindowsApps", StringComparison.OrdinalIgnoreCase)) continue;
            string candidate = Path.Combine(path, "python.exe");
            if (ValidPython(candidate, root)) return candidate;
            string py = Path.Combine(path, "py.exe");
            if (File.Exists(py)) {
                try {
                    candidate = Capture(py, "-3.12 -I -c \"import sys; print(sys.executable)\"", root);
                    if (ValidPython(candidate, root)) return candidate;
                } catch (IOException) { }
            }
        }
        return null;
    }
    internal static string Hex(byte[] bytes) { return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant(); }
    internal static string Digest(Stream stream) { using (var hash = SHA256.Create()) return Hex(hash.ComputeHash(stream)); }
    internal static string InstanceIdentity(string root) {
        using (var hash = SHA256.Create()) return Hex(hash.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(root).TrimEnd('\\') + "my-fish"))).Substring(0, 24);
    }
    internal static bool TryFocus(string root) {
        string identity = InstanceIdentity(root);
        try {
            using (var mutex = Mutex.OpenExisting("Local\\FatfishDesktop-" + identity)) {
                File.WriteAllText(Path.Combine(root, ".runtime", "focus-" + identity), "focus");
                return true;
            }
        } catch (WaitHandleCannotBeOpenedException) { return false; }
    }
    internal static void AssertNotRunning(string root) {
        string identity = InstanceIdentity(root);
        try {
            using (var mutex = Mutex.OpenExisting("Local\\FatfishDesktop-" + identity))
                throw new IOException("此位置的千鱼正在运行，请先正常退出再安装。");
        } catch (WaitHandleCannotBeOpenedException) { }
    }
    internal static void AssertNoDirectoryLinks(string root, string target) {
        for (string parent = Path.GetDirectoryName(target); parent != null && parent.Length >= root.Length; parent = Path.GetDirectoryName(parent))
            if (Directory.Exists(parent) && (File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0)
                throw new IOException("安装目录中存在目录链接，请改用独立的普通文件夹。");
    }
    internal static string Download(string url, string destination) {
        if (!url.StartsWith("https://", StringComparison.OrdinalIgnoreCase)) throw new IOException("下载必须使用 HTTPS。");
        Directory.CreateDirectory(Path.GetDirectoryName(destination));
        ServicePointManager.SecurityProtocol = (SecurityProtocolType)3072;
        string temporary = destination + ".download";
        using (var client = new WebClient()) client.DownloadFile(url, temporary);
        if (File.Exists(destination)) File.Delete(destination);
        File.Move(temporary, destination);
        return destination;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct TrustFile { public uint Size; public string Path; public IntPtr File; public IntPtr Subject; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct TrustData {
        public uint Size; public IntPtr Policy; public IntPtr Sip; public uint Ui; public uint Revocation;
        public uint Choice; public IntPtr File; public uint StateAction; public IntPtr State;
        public string Url; public uint Flags; public uint Context;
    }
    [DllImport("wintrust.dll", ExactSpelling = true, CharSet = CharSet.Unicode)]
    private static extern int WinVerifyTrust(IntPtr window, [In] ref Guid action, [In] ref TrustData data);
    internal static void VerifyPublisher(string path, string publisher) {
        var file = new TrustFile { Size = (uint)Marshal.SizeOf(typeof(TrustFile)), Path = path };
        IntPtr memory = Marshal.AllocHGlobal(Marshal.SizeOf(typeof(TrustFile)));
        try {
            Marshal.StructureToPtr(file, memory, false);
            var data = new TrustData { Size = (uint)Marshal.SizeOf(typeof(TrustData)), Ui = 2, Revocation = 1, Choice = 1, File = memory };
            var action = new Guid("00AAC56B-CD44-11d0-8CC2-00C04FC295EE");
            int trustResult = WinVerifyTrust(new IntPtr(-1), ref action, ref data);
            if (trustResult != 0) throw new IOException("官方安装器签名校验失败（0x" + unchecked((uint)trustResult).ToString("X8") + "），已停止安装：" + path);
            var cert = new X509Certificate2(X509Certificate.CreateFromSignedFile(path));
            if (cert.Subject.IndexOf(publisher, StringComparison.OrdinalIgnoreCase) < 0) throw new IOException("官方安装器发布者不匹配。");
        } finally { Marshal.DestroyStructure(memory, typeof(TrustFile)); Marshal.FreeHGlobal(memory); }
    }
    internal static void RunOfficialInstaller(string path, string publisher, string root) {
        VerifyPublisher(path, publisher);
        using (var p = Process.Start(new ProcessStartInfo(path) { WorkingDirectory = root, UseShellExecute = true, WindowStyle = ProcessWindowStyle.Normal })) {
            p.WaitForExit(); if (p.ExitCode != 0 && p.ExitCode != 3010) throw new IOException("官方组件安装未完成，退出码：" + p.ExitCode);
        }
    }
    internal static void CreateShortcut(string root) {
        object shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell")), shortcut = null;
        try {
            string path = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "千鱼.lnk");
            shortcut = shell.GetType().InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            Type type = shortcut.GetType();
            foreach (var pair in new Dictionary<string, object> {
                { "TargetPath", Path.Combine(root, "千鱼.exe") }, { "Arguments", "" }, { "WorkingDirectory", root },
                { "Description", "千鱼" }, { "IconLocation", Path.Combine(root, "fatfish", "web", "assets", "qianyu.ico") + ",0" }
            }) type.InvokeMember(pair.Key, BindingFlags.SetProperty, null, shortcut, new object[] { pair.Value });
            type.InvokeMember("Save", BindingFlags.InvokeMethod, null, shortcut, null);
        } finally {
            if (shortcut != null) Marshal.FinalReleaseComObject(shortcut);
            Marshal.FinalReleaseComObject(shell);
        }
    }
}
