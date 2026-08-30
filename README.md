# agent-sync

Keep instructions and skills in sync across multiple coding agents (Claude
Code, Codex, opencode, Junie, pi, ...) from one git-tracked master.

- **One master, many agents.** `master/AGENTS.md` is the canonical
  instructions file; each agent's own instructions file (`CLAUDE.md`,
  `AGENTS.md`, ...) is linked to it. `master/skills/<name>/` is the canonical
  copy of each skill; each agent's `skills/<name>` is linked to it.
- **Per-skill linking, not whole-directory.** Skills installed only for one
  agent (e.g. a codex-specific plugin) are left alone — only skills present in
  master get linked out.
- **Symlink with copy fallback.** Tries a real symlink first; falls back to a
  tracked copy + content hash when the OS/permissions don't allow symlinks
  (e.g. Windows without Developer Mode/admin). Fallback copies are detected as
  drifted (`status`) once master changes, and refreshed on the next `link`.
- **Skills pulled from git sources.** Point at any repo with `SKILL.md` files
  (flat or nested under category folders) and pull/update/discover/adopt
  skills from it.
- **Master content isn't versioned skill-by-skill in this repo.**
  `master/skills/` is gitignored — it's synced *from* upstream sources
  (`.skill-lock.json` records provenance), not authored here. What's tracked
  is the tool, the config that says what to sync, and the hand-authored
  instructions file.

## Requirements

- [uv](https://docs.astral.sh/uv/) (runs the script's inline PEP 723
  dependencies automatically)
- `git` on `PATH`

## Setup

```sh
uv run agent_sync.py init
```

Creates `master/` and an empty `config.yaml`. Edit `config.yaml` to describe
your agents and skill sources:

```yaml
agents:
  claude:
    instructions:
      path: "~/.claude/CLAUDE.md"
      master: "AGENTS.md"
    skills_dir: "~/.claude/skills"
  codex:
    instructions:
      path: "~/.codex/AGENTS.md"
      master: "AGENTS.md"
    skills_dir: "~/.codex/skills"

sources:
  - name: antfu-skills
    url: "https://github.com/antfu/skills.git"
    subdir: "skills"
    mode: multi   # repo contains many skills under subdir (flat or nested)
```

## Commands

| Command | What it does |
|---|---|
| `link [--agent NAME] [--force]` | Symlink/copy each agent's instructions + skills from master. `--force` overwrites a drifted instructions file. |
| `status [--agent NAME]` | Show link/copy/drift state per agent. |
| `diff <agent> [--skill NAME]` | Diff an agent's instructions (or one skill) against master. |
| `pull [--source NAME] [--add SKILL]` | Refresh already-adopted skills from their source repos. |
| `discover [--source NAME]` | List skills available in a source but not yet in master. |
| `add <skill> [--source NAME]` | Adopt a newly discovered skill into `master/skills/`. |
| `sync` | `pull` all sources, then `link` all agents. |

Typical flow after editing an instructions file or wanting upstream skill
updates:

```sh
uv run agent_sync.py status         # see what's drifted
uv run agent_sync.py pull           # refresh installed skills from sources
uv run agent_sync.py link           # relink everything
```

## Adding a new skill from a source

```sh
uv run agent_sync.py discover --source antfu-skills   # see what's new
uv run agent_sync.py add vue --source antfu-skills     # adopt it
uv run agent_sync.py link                              # sync to all agents
```

## Notes

- Windows symlinks require Developer Mode or an elevated shell. Without it,
  `link` falls back to tracked copies automatically — no action needed, but
  re-run `link` from an elevated session later to upgrade fallback copies to
  real symlinks.
- A real, unmanaged skill folder already in an agent's `skills_dir` (not
  previously linked from master) is left untouched and reported as `[local]`.
- Instructions-file conflicts (an agent's file has diverged from master) are
  never silently overwritten; `link` reports `[CONFLICT]` and requires
  `--force`.

## Credits

`master/AGENTS.md`'s global instructions are adapted from
[Anbeeld/AGENTS.md](https://github.com/Anbeeld/AGENTS.md).

## License

[MIT](LICENSE)
