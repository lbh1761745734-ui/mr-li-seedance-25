#!/usr/bin/env python3
"""Install this skill for the current user, with verified copies and rollback."""

from pathlib import Path

# Display the complete attribution and acknowledgements before argument parsing.
NOTICE_PATH = Path(__file__).absolute().parent.parent / "CREDITS.md"
print(NOTICE_PATH.read_text(encoding="utf-8").strip(), flush=True)

import argparse
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid


SKILL_NAME = "mr-li-seedance-25"
REQUIRED_FILES = ("SKILL.md", "CREDITS.md", "INSTALL.md", "agents/openai.yaml", "scripts/install.py")

IGNORED_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".git", ".DS_Store", "node_modules"}


def ignored(name):
    return name in IGNORED_NAMES or name.endswith((".pyc", ".pyo"))


def metadata(root):
    """Read this package's restricted name + metadata.version YAML format."""
    text = (root / "SKILL.md").read_text(encoding="utf-8-sig")
    front = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|$)", text, re.S)
    if not front:
        raise ValueError(f"SKILL.md 缺少有效的 YAML 开头：{root}")

    def scalar(line, key, indent=""):
        pattern = rf"^{indent}{key}:[ \t]*(?:\"([^\"]+)\"|'([^']+)'|([^#\s]+))[ \t]*(?:#.*)?$"
        match = re.match(pattern, line)
        return next((v for v in match.groups() if v is not None), None) if match else None

    names, versions = [], []
    in_metadata = False
    for line in front.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        value = scalar(line, "name")
        if value is not None:
            names.append(value)
        if re.match(r"^metadata:[ \t]*(?:#.*)?$", line):
            in_metadata = True
            continue
        if not line[0].isspace():
            in_metadata = False
        if in_metadata:
            value = scalar(line, "version", r"[ \t]+")
            if value is not None:
                versions.append(value)
    if len(names) != 1 or len(versions) != 1 or not re.fullmatch(r"v?\d+(?:\.\d+)*", versions[0]):
        raise ValueError(f"SKILL.md 必须含唯一 name 和 metadata.version：{root}")
    return names[0], versions[0].removeprefix("v")


def validate_source(root):
    if root.is_symlink() or not root.is_dir():
        raise ValueError("源技能必须是普通目录，不能是符号链接")
    # Inspect all source entries, including ignored cache folders. Never follow
    # or silently dereference a symlink supplied inside the skill package.
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in folders + files:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"源技能含符号链接，拒绝安装：{Path(directory) / name}")
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ValueError("源技能缺少必需文件：" + "、".join(missing))
    name, version = metadata(root)
    if name != SKILL_NAME:
        raise ValueError(f"源技能 name 应为 {SKILL_NAME}，实际为 {name}")
    return version


def file_manifest(root):
    result = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(name for name in folders if not ignored(name))
        for name in sorted(files):
            if ignored(name):
                continue
            path = Path(directory) / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"技能中存在非普通文件：{path}")
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def install_skill(source, skills_dir, replace=False):
    version = validate_source(source)
    source = source.resolve()
    skills_dir = skills_dir.expanduser().resolve()
    target = skills_dir / SKILL_NAME
    if target.is_symlink():
        raise ValueError(f"目标是符号链接，拒绝安装：{target}")
    if target == source:
        return {"target": target, "version": version, "already_installed": True, "backup": None}
    if source in target.parents or target in source.parents:
        raise ValueError("源技能与目标技能不能互相包含")
    if skills_dir == source or source in skills_dir.parents:
        raise ValueError("安装目录不能放在源技能内部")

    def check_target():
        if target.is_symlink():
            raise ValueError(f"目标是符号链接，拒绝安装：{target}")
        if target.exists():
            if not target.is_dir() or metadata(target)[0] != SKILL_NAME:
                raise ValueError(f"目标不是同名技能，拒绝覆盖：{target}")
            if not replace:
                raise ValueError(f"技能已存在；需要备份并替换时请显式使用 --replace：{target}")

    check_target()
    expected = file_manifest(source)
    skills_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}-install-", dir=skills_dir))
    backup = None
    installed = False
    try:
        shutil.copytree(source, staging, dirs_exist_ok=True,
                        ignore=lambda _directory, names: [name for name in names if ignored(name)])
        if file_manifest(staging) != expected:
            raise RuntimeError("安装副本与源文件的 SHA256 不一致，未替换旧技能")
        # Recheck just before the directory swap; an existing target always
        # requires --replace, even if it appeared after the first check.
        check_target()
        if target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = skills_dir / f".{SKILL_NAME}-backup-{stamp}-{uuid.uuid4().hex[:8]}"
            target.rename(backup)
        staging.rename(target)
        installed = True
        if file_manifest(target) != expected:
            raise RuntimeError("安装后文件 SHA256 校验失败")
    except BaseException as error:
        try:
            if installed and target.exists():
                shutil.rmtree(target)
            if backup is not None and backup.exists():
                backup.rename(target)
        except OSError as rollback_error:
            raise RuntimeError(f"安装失败，自动恢复未完成；旧技能备份保留于 {backup}。"
                               f"恢复错误：{rollback_error}；原错误：{error}") from error
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return {"target": target, "version": version, "already_installed": False, "backup": backup}


def main(argv=None):
    parser = argparse.ArgumentParser(description="安装李先生AI影视全流程Skill到个人技能目录")
    default_base = Path(os.environ["CODEX_HOME"]).expanduser() if os.environ.get("CODEX_HOME") else Path.home() / ".codex"
    parser.add_argument("--skills-dir", type=Path, default=default_base / "skills", help="安装目录；默认 CODEX_HOME/skills 或 ~/.codex/skills")
    parser.add_argument("--replace", action="store_true", help="先保留旧技能隐藏备份，再替换安装")
    args = parser.parse_args(argv)
    try:
        script = Path(__file__).absolute()
        if script.is_symlink():
            raise ValueError("请直接运行技能中的 scripts/install.py，不通过符号链接运行")
        result = install_skill(script.parent.parent, args.skills_dir, args.replace)
        label = "已安装于此目录，无需复制" if result["already_installed"] else "安装成功，文件 SHA256 校验通过"
        print(f"{label}：李先生AI影视全流程Skill v{result['version']}\n{result['target']}")
        if result["backup"]:
            print(f"旧技能备份：{result['backup']}")
        return 0
    except Exception as exc:
        print(f"安装失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
