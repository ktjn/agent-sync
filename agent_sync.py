# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml"]
# ///
"""agent-sync: keep AGENTS.md/instructions and skills in sync across coding agents.

Master copies live in master/ (git-tracked, this repo). Each configured agent
gets:
  - an `instructions` symlink (its own filename, e.g. CLAUDE.md) -> master/AGENTS.md
  - per-skill symlinks inside its skills_dir -> master/skills/<name>

Per-skill (not whole-directory) linking so agent-local-only skills (e.g. a
skill only installed for codex) are left untouched.

Falls back to a tracked copy + hash when symlinks aren't permitted (no
Developer Mode / admin on Windows).

Skill sources are git repos pulled into master/skills/<name>.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
MASTER_DIR = ROOT / "master"
CONFIG_PATH = ROOT / "config.yaml"
MANIFEST_PATH = MASTER_DIR / ".manifest.json"
SOURCES_CACHE = ROOT / ".sources"


# ---------- config / manifest ----------

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"agents": {}, "sources": []}
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {"agents": {}, "sources": []}


def save_config(cfg: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, sort_keys=False)


def load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {}
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)


def selected_agents(cfg: dict, name: str | None) -> dict:
    agents = cfg.get("agents", {})
    if name is None:
        return agents
    if name not in agents:
        print(f"No configured agent named: {name}", file=sys.stderr)
        sys.exit(1)
    return {name: agents[name]}


# ---------- hashing ----------

def hash_path(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
    elif path.is_dir():
        for p in sorted(path.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(path)).encode())
                h.update(p.read_bytes())
    else:
        return ""
    return h.hexdigest()


def contents_equal(a: Path, b: Path) -> bool:
    if not a.exists() or not b.exists():
        return False
    return hash_path(a) == hash_path(b)


# ---------- single link op (symlink w/ copy fallback) ----------

def is_link(path: Path) -> bool:
    """True for symlinks/junctions, including broken ones.

    Windows: Path.is_symlink()/.exists() both report False for a broken
    reparse point, so detect via readlink success instead.
    """
    if path.is_symlink():
        return True
    if not os.path.lexists(path):
        return False
    try:
        os.readlink(path)
        return True
    except OSError:
        return False


def remove_any(path: Path) -> None:
    """Remove a file, symlink, or (possibly broken) dir junction/symlink."""
    if not os.path.lexists(path):
        return
    try:
        os.remove(path)  # files and file-symlinks
        return
    except OSError:
        pass
    try:
        os.rmdir(path)  # dir symlinks / junctions (incl. broken ones)
        return
    except OSError:
        pass
    shutil.rmtree(path)  # real directory with content


def link_one(src: Path, dst: Path) -> str:
    """Make dst a symlink to src (or tracked copy on failure). Returns mode."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    remove_any(dst)
    try:
        dst.symlink_to(src, target_is_directory=src.is_dir())
        return "symlink"
    except OSError:
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return "copy"


# ---------- link command ----------

def cmd_link(args: argparse.Namespace) -> None:
    cfg = load_config()
    manifest = load_manifest()
    agents = selected_agents(cfg, args.agent)

    for agent_name, agent in agents.items():
        print(f"[{agent_name}]")

        instr = agent.get("instructions")
        if instr:
            target_path = Path(instr["path"]).expanduser()
            src = MASTER_DIR / instr["master"]
            if not src.exists():
                print(f"  [skip] master source missing: {src}", file=sys.stderr)
            elif target_path.exists() and not target_path.is_symlink() and not contents_equal(target_path, src):
                print(f"  [CONFLICT] {target_path} differs from master/{instr['master']}; "
                      f"not overwriting. Resolve with 'diff' then --force to overwrite.")
                if not args.force:
                    pass
                else:
                    mode = link_one(src, target_path)
                    manifest[str(target_path)] = {"master": instr["master"], "mode": mode}
                    if mode == "copy":
                        manifest[str(target_path)]["hash"] = hash_path(target_path)
                    print(f"  [{mode}] (forced) {target_path} -> master/{instr['master']}")
            else:
                mode = link_one(src, target_path)
                manifest[str(target_path)] = {"master": instr["master"], "mode": mode}
                if mode == "copy":
                    manifest[str(target_path)]["hash"] = hash_path(target_path)
                print(f"  [{mode}] {target_path} -> master/{instr['master']}")

        skills_dir = agent.get("skills_dir")
        if skills_dir:
            skills_dir = Path(skills_dir).expanduser()
            skills_dir.mkdir(parents=True, exist_ok=True)
            master_skills = MASTER_DIR / "skills"
            if master_skills.exists():
                for skill in sorted(p for p in master_skills.iterdir() if p.is_dir()):
                    dst = skills_dir / skill.name
                    # only touch entries that are (or were already) managed by us;
                    # an unmanaged real dir here is a local-only skill -> leave it.
                    already_managed = manifest.get(str(dst), {}).get("master") == f"skills/{skill.name}"
                    if os.path.lexists(dst) and not is_link(dst) and not already_managed:
                        print(f"  [local] {dst.name} (agent-local skill, left untouched)")
                        continue
                    mode = link_one(skill, dst)
                    manifest[str(dst)] = {"master": f"skills/{skill.name}", "mode": mode}
                    if mode == "copy":
                        manifest[str(dst)]["hash"] = hash_path(dst)
                    print(f"  [{mode}] skills/{skill.name}")

    save_manifest(manifest)


# ---------- status / diff ----------

def _status_one(label: str, target_path: Path, src: Path, manifest: dict) -> None:
    if not os.path.lexists(target_path):
        print(f"MISSING   {label:40s} {target_path}")
        return
    if is_link(target_path):
        resolved = target_path.resolve()
        if not target_path.exists():
            print(f"BROKEN    {label:40s} {target_path} -> (dangling), expected {src}")
        elif resolved == src.resolve():
            print(f"OK(link)  {label:40s} {target_path}")
        else:
            print(f"STALE     {label:40s} {target_path} -> {resolved}, expected {src}")
        return
    entry = manifest.get(str(target_path))
    current_hash = hash_path(target_path)
    master_hash = hash_path(src)
    if current_hash == master_hash:
        print(f"OK(copy)  {label:40s} {target_path}")
    elif entry and entry.get("hash") and current_hash != entry["hash"]:
        print(f"DRIFTED   {label:40s} {target_path}  (local edits since last sync)")
    else:
        print(f"OUTDATED  {label:40s} {target_path}  (master changed, run link)")


def cmd_status(args: argparse.Namespace) -> None:
    cfg = load_config()
    manifest = load_manifest()
    agents = selected_agents(cfg, args.agent)
    if not agents:
        print("No agents configured.")
        return

    for agent_name, agent in agents.items():
        print(f"[{agent_name}]")
        instr = agent.get("instructions")
        if instr:
            _status_one("instructions", Path(instr["path"]).expanduser(), MASTER_DIR / instr["master"], manifest)
        skills_dir = agent.get("skills_dir")
        if skills_dir:
            skills_dir = Path(skills_dir).expanduser()
            master_skills = MASTER_DIR / "skills"
            if master_skills.exists():
                for skill in sorted(p for p in master_skills.iterdir() if p.is_dir()):
                    dst = skills_dir / skill.name
                    if not dst.exists():
                        print(f"MISSING   skills/{skill.name:32s} {dst}")
                        continue
                    _status_one(f"skills/{skill.name}", dst, skill, manifest)


def cmd_diff(args: argparse.Namespace) -> None:
    cfg = load_config()
    agent = cfg.get("agents", {}).get(args.agent)
    if not agent:
        print(f"No configured agent named: {args.agent}", file=sys.stderr)
        sys.exit(1)
    if args.skill:
        target_path = Path(agent["skills_dir"]).expanduser() / args.skill
        src = MASTER_DIR / "skills" / args.skill
    else:
        instr = agent.get("instructions")
        if not instr:
            print(f"Agent {args.agent} has no instructions file configured.", file=sys.stderr)
            sys.exit(1)
        target_path = Path(instr["path"]).expanduser()
        src = MASTER_DIR / instr["master"]
    subprocess.run(["diff", "-ru", str(src), str(target_path)])


# ---------- skill sources (git) ----------

def clone_or_update(source_name: str, url: str, ref: str | None) -> Path:
    SOURCES_CACHE.mkdir(exist_ok=True)
    clone_dir = SOURCES_CACHE / source_name
    if clone_dir.exists():
        print(f"[{source_name}] fetching updates...")
        subprocess.run(["git", "-C", str(clone_dir), "fetch", "--depth", "1", "origin", ref or "HEAD"], check=True)
        subprocess.run(["git", "-C", str(clone_dir), "reset", "--hard", "FETCH_HEAD"], check=True)
    else:
        print(f"[{source_name}] cloning {url}...")
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(clone_dir)]
        subprocess.run(cmd, check=True)
    return clone_dir


def is_skill_folder(path: Path) -> bool:
    return (path / "SKILL.md").exists()


def find_skill_folders(container: Path):
    """Recursively find skill folders under container (handles category
    subdirs like mattpocock/skills's skills/engineering/<name>), skipping
    .git. Yields dirs whose own SKILL.md exists, not their ancestors."""
    for skill_md in sorted(container.rglob("SKILL.md")):
        if ".git" in skill_md.parts:
            continue
        yield skill_md.parent


def copy_skill(skill_src: Path, name: str) -> str:
    """Copy skill_src into master/skills/<name>. Returns 'new'/'updated'/'unchanged'."""
    skill_dst = MASTER_DIR / "skills" / name
    old_hash = hash_path(skill_dst) if skill_dst.exists() else None
    existed = skill_dst.exists()
    if existed:
        shutil.rmtree(skill_dst)
    shutil.copytree(skill_src, skill_dst, ignore=shutil.ignore_patterns(".git"))
    new_hash = hash_path(skill_dst)
    if not existed:
        return "new"
    return "unchanged" if old_hash == new_hash else "updated"


def cmd_pull(args: argparse.Namespace) -> None:
    """Update already-installed skills from their source repos.

    Multi-skill sources only touch skills already present in master/skills;
    use `discover`/`--add` to bring in new ones on purpose.
    """
    cfg = load_config()
    sources = cfg.get("sources", [])
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            print(f"No configured source named: {args.source}", file=sys.stderr)
            sys.exit(1)

    (MASTER_DIR / "skills").mkdir(parents=True, exist_ok=True)
    installed = {p.name for p in (MASTER_DIR / "skills").iterdir() if p.is_dir()}

    for s in sources:
        name = s["name"]
        clone_dir = clone_or_update(name, s["url"], s.get("ref"))
        subdir = s.get("subdir", "")
        container = clone_dir / subdir if subdir else clone_dir
        mode = s.get("mode", "single")

        if mode == "multi":
            if not container.exists():
                print(f"  [warn] subdir not found in {name}: {subdir}", file=sys.stderr)
                continue
            for child in find_skill_folders(container):
                if child.name not in installed:
                    continue  # not yet adopted; see `discover` / `pull --add`
                result = copy_skill(child, child.name)
                print(f"  [{child.name}] {result}")
        else:
            skill_src = container
            if not skill_src.exists():
                print(f"  [warn] subdir not found in {name}: {subdir}", file=sys.stderr)
                continue
            result = copy_skill(skill_src, name)
            print(f"  [{name}] {result}")

    if args.add:
        cmd_add(argparse.Namespace(source=args.source, skill=args.add))


def cmd_discover(args: argparse.Namespace) -> None:
    """List skills available in configured sources that aren't in master yet."""
    cfg = load_config()
    sources = cfg.get("sources", [])
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            print(f"No configured source named: {args.source}", file=sys.stderr)
            sys.exit(1)

    (MASTER_DIR / "skills").mkdir(parents=True, exist_ok=True)
    installed = {p.name for p in (MASTER_DIR / "skills").iterdir() if p.is_dir()}

    for s in sources:
        name = s["name"]
        clone_dir = clone_or_update(name, s["url"], s.get("ref"))
        subdir = s.get("subdir", "")
        container = clone_dir / subdir if subdir else clone_dir
        mode = s.get("mode", "single")

        print(f"[{name}]")
        if mode == "multi":
            if not container.exists():
                print(f"  [warn] subdir not found: {subdir}", file=sys.stderr)
                continue
            found_new = False
            for child in find_skill_folders(container):
                if child.name not in installed:
                    print(f"  NEW  {child.name}")
                    found_new = True
            if not found_new:
                print("  (no new skills; all present in master)")
        else:
            if name not in installed and container.exists():
                print(f"  NEW  {name}")
            else:
                print("  (already installed or subdir missing)")


def cmd_add(args: argparse.Namespace) -> None:
    """Adopt a newly discovered skill from a source into master/skills."""
    cfg = load_config()
    sources = cfg.get("sources", [])
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
    if not sources:
        print("No matching source configured.", file=sys.stderr)
        sys.exit(1)

    for s in sources:
        clone_dir = SOURCES_CACHE / s["name"]
        if not clone_dir.exists():
            clone_dir = clone_or_update(s["name"], s["url"], s.get("ref"))
        subdir = s.get("subdir", "")
        container = clone_dir / subdir if subdir else clone_dir
        mode = s.get("mode", "single")

        if mode == "multi":
            candidate = next((p for p in find_skill_folders(container) if p.name == args.skill), None)
        else:
            candidate = container if s["name"] == args.skill else None

        if candidate and candidate.exists() and is_skill_folder(candidate):
            result = copy_skill(candidate, args.skill)
            print(f"[{s['name']}] added skills/{args.skill} ({result})")
            return

    print(f"Skill '{args.skill}' not found in configured source(s).", file=sys.stderr)
    sys.exit(1)


# ---------- init / sync ----------

def cmd_init(args: argparse.Namespace) -> None:
    MASTER_DIR.mkdir(exist_ok=True)
    (MASTER_DIR / "skills").mkdir(exist_ok=True)
    instructions_md = MASTER_DIR / "CLAUDE.md"
    if not instructions_md.exists():
        instructions_md.write_text("# Instructions\n\nMaster instructions shared across agents.\n", encoding="utf-8")
    if not CONFIG_PATH.exists():
        save_config({"agents": {}, "sources": []})
        print(f"Created {CONFIG_PATH} (add agents + sources for your setup)")
    print(f"Master dir ready at {MASTER_DIR}")


def cmd_sync(args: argparse.Namespace) -> None:
    cmd_pull(argparse.Namespace(source=None, add=None))
    cmd_link(argparse.Namespace(agent=None, force=False))


# ---------- CLI ----------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create master/ dir and empty config.yaml")

    p_link = sub.add_parser("link", help="symlink (or copy-fallback) each agent to master")
    p_link.add_argument("--agent", help="only link this agent")
    p_link.add_argument("--force", action="store_true", help="overwrite drifted instructions files")

    p_status = sub.add_parser("status", help="show drift between master and each agent")
    p_status.add_argument("--agent", help="only show this agent")

    p_diff = sub.add_parser("diff", help="diff one agent's instructions or a skill vs master")
    p_diff.add_argument("agent")
    p_diff.add_argument("--skill", help="diff this skill instead of the instructions file")

    p_pull = sub.add_parser("pull", help="update already-installed skills from their source repos")
    p_pull.add_argument("--source", help="only pull this source name")
    p_pull.add_argument("--add", help="also adopt this new skill by name after pulling")

    p_discover = sub.add_parser("discover", help="list skills available in sources but not yet in master")
    p_discover.add_argument("--source", help="only check this source name")

    p_add = sub.add_parser("add", help="adopt a newly discovered skill into master/skills")
    p_add.add_argument("skill", help="skill name (folder name in the source)")
    p_add.add_argument("--source", help="restrict to this source name")

    sub.add_parser("sync", help="pull all sources then relink all agents")

    args = parser.parse_args()
    {
        "init": cmd_init,
        "link": cmd_link,
        "status": cmd_status,
        "diff": cmd_diff,
        "pull": cmd_pull,
        "discover": cmd_discover,
        "add": cmd_add,
        "sync": cmd_sync,
    }[args.command](args)


if __name__ == "__main__":
    main()
