# agent-sync

Synchronizes instructions and skills across coding agents from a single git-tracked `master/` directory.

## Architecture & Layout

- `agent_sync.py`: Single-file CLI script with inline PEP 723 dependencies (run via `uv`).
- `config.yaml`: Defines target `agents` (instruction paths, `skills_dir`) and upstream git `sources`.
- `master/AGENTS.md`: Canonical global instructions linked to each configured agent.
- `master/skills/<name>/`: Canonical skill directories linked per-skill into each agent's `skills_dir`.
- `master/.manifest.json`: Tracks managed links, copies, and content hashes (gitignored).
- `.sources/`: Cached upstream skill git repositories (gitignored).

## Linking & Sync Behavior

- Links only skills present in `master/skills/`; unmanaged agent-local skills are preserved (`[local]`).
- Link strategy fallback order:
  - Skills: symlink -> Windows NTFS junction -> tracked copy.
  - Instructions: symlink -> hardlink (same volume) -> tracked copy.
- Diverged agent instruction files report `[CONFLICT]` and require `link --force` to overwrite.

## Repository Rules & Constraints

- Run all commands with `uv run agent_sync.py <command>` (`git` required on `PATH`).
- Do not edit upstream-sourced skills under `master/skills/`; `pull` and `sync` replace entire skill folders.
- Four customized skill entrypoints are versioned in git (`.gitignore` exceptions):
  - `master/skills/antfu/SKILL.md`
  - `master/skills/browse-chrome/SKILL.md`
  - `master/skills/frontend-design/SKILL.md`
  - `master/skills/using-git-worktrees/SKILL.md`
- Preserve local changes in those four `SKILL.md` files when running `pull` or `sync`, as folder replacement overwrites them.

## CLI Commands

- `uv run agent_sync.py init`: Create `master/` and empty `config.yaml`.
- `uv run agent_sync.py status [--agent NAME]`: Show link, copy, and drift state.
- `uv run agent_sync.py diff <agent> [--skill NAME]`: Diff agent instructions or skill against `master/`.
- `uv run agent_sync.py link [--agent NAME] [--force]`: Link instructions and skills from `master/` to agents.
- `uv run agent_sync.py pull [--source NAME] [--add SKILL]`: Refresh adopted skills from upstream sources.
- `uv run agent_sync.py discover [--source NAME]`: List skills in sources not yet in `master/skills/`.
- `uv run agent_sync.py add <skill> [--source NAME]`: Adopt a skill from a source into `master/skills/`.
- `uv run agent_sync.py sync`: Run `pull` for all sources followed by `link` for all agents.
