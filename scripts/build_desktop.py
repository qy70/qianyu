"""Build native Windows entry points, clean payload and release checksums."""
from pathlib import Path
import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish import __version__
from fatfish.layout import share_dir
from scripts.build_release import build


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--certificate-thumbprint")
    parser.add_argument("--signtool", default=shutil.which("signtool.exe"))
    parser.add_argument("--require-signature", action="store_true")
    args = parser.parse_args()
    if args.require_signature and not args.certificate_thumbprint:
        parser.error("正式签名构建必须提供 --certificate-thumbprint；不能把未签名文件标为已签名发行版。")
    if args.certificate_thumbprint and not args.signtool:
        parser.error("签名需要 Windows SDK 的 signtool.exe。")
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET/Framework64/v4.0.30319/csc.exe"
    output = (args.output or share_dir(ROOT)).resolve()
    output.mkdir(parents=True, exist_ok=True)
    build_dir = ROOT / ".runtime/build"
    build_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_dir / "AssemblyInfo.cs"
    metadata.write_text(
        'using System.Reflection;\n[assembly: AssemblyTitle("千鱼")]\n'
        '[assembly: AssemblyProduct("千鱼")]\n[assembly: AssemblyDescription("千鱼 Windows 安装与启动程序")]\n'
        f'[assembly: AssemblyVersion("{__version__}.0")]\n[assembly: AssemblyFileVersion("{__version__}.0")]\n'
        f'internal static class BuildInfo {{ internal const string Version = "{__version__}"; }}\n', encoding="utf-8")

    def sign(path):
        if not args.certificate_thumbprint:
            return
        subprocess.run([args.signtool, "sign", "/sha1", args.certificate_thumbprint, "/fd", "SHA256",
                        "/tr", "http://timestamp.digicert.com", "/td", "SHA256", str(path)], check=True)
        subprocess.run([args.signtool, "verify", "/pa", "/all", str(path)], check=True)

    def compile_entry(source, target, console=False, payload=None):
        command = [str(compiler), "/nologo", "/codepage:65001", "/target:" + ("exe" if console else "winexe"),
                   "/reference:System.Windows.Forms.dll", "/reference:System.Drawing.dll", "/reference:System.Web.Extensions.dll",
                   "/reference:System.IO.Compression.dll", "/win32icon:" + str(ROOT / "fatfish/web/assets/qianyu.ico"),
                   "/out:" + str(target), str(ROOT / "scripts" / source), str(ROOT / "scripts/DesktopSupport.cs"), str(metadata)]
        if payload:
            command.append("/resource:" + str(payload) + ",payload.zip")
        if source == "Setup.cs":
            command.append(str(ROOT / "scripts/UpdateSetup.cs"))
        subprocess.run(command, cwd=ROOT, check=True)
        sign(target)

    compile_entry("Launcher.cs", ROOT / "千鱼.exe")
    compile_entry("Setup.cs", ROOT / "千鱼安装助手.exe", console=True)
    package = build(output=output / f"千鱼-{__version__}-纯净版.zip")
    installer = output / f"千鱼-{__version__}-安装.exe"
    compile_entry("Installer.cs", installer, payload=package)
    manual = output / f"千鱼-{__version__}-操作手册.pdf"
    shutil.copyfile(ROOT / "templates/distribution/操作手册.pdf", manual)
    artifacts = []
    for path in (installer, package, manual):
        artifacts.append({"file": path.name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    status = "signed_and_verified" if args.certificate_thumbprint else "unsigned_preview"
    report = {"product": "千鱼", "version": __version__, "built_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
              "signing_status": status, "powershell_script_required_for_install_or_launch": False,
              "artifacts": artifacts}
    (output / f"千鱼-{__version__}-发布校验.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / f"SHA256SUMS-{__version__}.txt").write_text("".join(f'{item["sha256"]}  {item["file"]}\n' for item in artifacts), encoding="utf-8")
    print(f"构建完成：{installer}\n签名状态：{status}")


if __name__ == "__main__":
    main()
