"""Installer transaction driver; uses no real chat/model requests."""
from pathlib import Path

import argparse
import json
import os
import site
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fatfish.updater import Upgrade, save
from scripts.windows_setup import prepare


def install(source: Path, target: Path, prepare_dependencies=prepare):
    transaction = Upgrade(source, target, owner_pid=os.getpid())
    try:
        transaction.apply()
        prepare_dependencies(transaction.program, rollback_directory=transaction.backup)
        packages = transaction.program / ".runtime/site-packages"
        sys.path.insert(0, str(packages))
        site.addsitedir(str(packages))
        transaction.migrate_defaults()
        return transaction.commit()
    except BaseException:
        if transaction.tx is not None:
            print("升级未完成，正在恢复原程序和配置；备份会保留。", flush=True)
            transaction.rollback()
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = install(args.source, args.target)
        save(args.result, report)
        print("安装/升级完成，记忆与知识校验通过。备份位置：" + report["backup"], flush=True)
    except Exception as error:
        print("安装/升级未完成：" + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
