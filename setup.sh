#!/bin/bash
#
# PaperOrchestra setup — configures skill discovery for all supported AI agents.
#
# Usage: bash setup.sh
#
# What it does:
#   1. Creates .env from .env.example (if not present) and prompts for API keys
#   2. Symlinks skills/* into each agent's expected skills directory:
#      - .claude/skills/    (Claude Code)
#      - .cursor/skills/    (Cursor)
#      - .windsurf/skills/  (Windsurf)
#      - .agents/skills/    (Antigravity / generic agents)
#   3. Symlinks all 9 skills globally into:
#      - ~/.claude/skills/               (Claude Code, global)
#      - ~/.agents/skills/               (OpenClaw + generic agents)
#      - ~/.codex/skills/                (Codex)
#      - ~/.gemini/antigravity/skills/   (Gemini)
#   4. Prints a summary of what's ready
#
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$SCRIPT_DIR/skills"

# Symlink every skill in SKILLS_DIR into TARGET_DIR.
# Skips real directories to avoid data loss; updates stale symlinks.
install_skills() {
  local target_dir="$1"
  local label="$2"
  mkdir -p "$target_dir"
  for skill in "$SKILLS_DIR"/*/; do
    local skill_name link_path
    skill_name="$(basename "$skill")"
    link_path="$target_dir/$skill_name"
    if [ -L "$link_path" ]; then
      rm "$link_path"
    elif [ -d "$link_path" ]; then
      echo "⚠️   $link_path is a real directory, skipping symlink"
      continue
    fi
    ln -s "${skill%/}" "$link_path"
  done
  echo "✅  Installed skills → $label"
}

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║         PaperOrchestra — Agent Setup             ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: .env ──────────────────────────────────────────────
if [ ! -f "$SCRIPT_DIR/.env" ]; then
  if [ -f "$SCRIPT_DIR/.env.example" ]; then
    cp "$SCRIPT_DIR/.env.example" "$SCRIPT_DIR/.env"
    echo "✅  Created .env from .env.example"
  else
    touch "$SCRIPT_DIR/.env"
    echo "✅  Created empty .env"
  fi
else
  echo "✅  .env already exists"
fi

# ── Step 1b: Prompt for environment variables ─────────────────
set_env_var() {
  local var_name="$1"
  local prompt_text="$2"
  local current_val=""

  if [ -f "$SCRIPT_DIR/.env" ]; then
    current_val=$(grep -E "^${var_name}=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2-)
  fi

  if [ -z "$current_val" ] || [ "$current_val" = "your_key_here" ] || [ "$current_val" = "" ]; then
    echo ""
    read -p "  $prompt_text (leave blank to skip): " input_val
    if [ -n "$input_val" ]; then
      if grep -qE "^${var_name}=" "$SCRIPT_DIR/.env" 2>/dev/null; then
        sed -i.bak "s|^${var_name}=.*|${var_name}=${input_val}|" "$SCRIPT_DIR/.env"
        rm -f "$SCRIPT_DIR/.env.bak"
      else
        echo "${var_name}=${input_val}" >> "$SCRIPT_DIR/.env"
      fi
      echo "  → ${var_name} saved to .env"
    else
      echo "  → Skipped ${var_name}"
    fi
  else
    echo "✅  ${var_name} already set"
  fi
}

set_env_var "SEMANTIC_SCHOLAR_API_KEY" "Semantic Scholar API key (SEMANTIC_SCHOLAR_API_KEY)"
set_env_var "EXA_API_KEY"              "Exa API key (EXA_API_KEY)"
set_env_var "PAPERBANANA_PATH"         "Path to PaperBanana executable (PAPERBANANA_PATH)"

# ── Step 1c: ~/.paperorchestra/config ─────────────────────────
GLOBAL_CONFIG_DIR="$HOME/.paperorchestra"
GLOBAL_CONFIG="$GLOBAL_CONFIG_DIR/config"
mkdir -p "$GLOBAL_CONFIG_DIR"

# Read values from .env
read_env_val() {
  grep -E "^${1}=" "$SCRIPT_DIR/.env" 2>/dev/null | cut -d'=' -f2- || echo ""
}

cat > "$GLOBAL_CONFIG" <<EOF
SEMANTIC_SCHOLAR_API_KEY=$(read_env_val SEMANTIC_SCHOLAR_API_KEY)
EXA_API_KEY=$(read_env_val EXA_API_KEY)
PAPERBANANA_PATH=$(read_env_val PAPERBANANA_PATH)
PAPERORCHESTRA_REPO=$SCRIPT_DIR
EOF
echo ""
echo "✅  Global config written to ~/.paperorchestra/config"

# ── Step 2: Symlink skills into local agent directories ───────
AGENT_DIRS=(
  ".claude/skills"
  ".cursor/skills"
  ".windsurf/skills"
  ".agents/skills"
)

for agent_dir in "${AGENT_DIRS[@]}"; do
  install_skills "$SCRIPT_DIR/$agent_dir" "$agent_dir/"
done

# ── Step 3: Install all 9 skills globally ─────────────────────
# OpenClaw discovers skills from ~/.agents/skills/ (per docs.openclaw.ai/skills);
# that path also covers OpenCode, Factory Droid, and any AGENTS.md-aware agent.
install_skills "$HOME/.claude/skills"              "~/.claude/skills/ (Claude Code, global)"
install_skills "$HOME/.agents/skills"              "~/.agents/skills/ (OpenClaw + generic)"
install_skills "$HOME/.codex/skills"               "~/.codex/skills/ (Codex)"
install_skills "$HOME/.gemini/antigravity/skills"  "~/.gemini/antigravity/skills/ (Gemini)"

# ── Step 4: Summary ──────────────────────────────────────────
SKILL_COUNT=$(ls -d "$SKILLS_DIR"/*/ 2>/dev/null | wc -l | tr -d ' ')

echo ""
echo "───────────────────────────────────────────────────"
echo " Setup complete!"
echo ""
echo " Skills installed: $SKILL_COUNT"
echo "   • agent-research-aggregator"
echo "   • content-refinement-agent"
echo "   • literature-review-agent"
echo "   • outline-agent"
echo "   • paper-autoraters"
echo "   • paper-orchestra"
echo "   • paper-writing-bench"
echo "   • plotting-agent"
echo "   • section-writing-agent"
echo ""
echo " Agents ready:    Claude Code, Cursor, Windsurf, Antigravity/Gemini, Codex, OpenClaw"
echo ""
echo " Environment variables (set in .env):"
echo "   SEMANTIC_SCHOLAR_API_KEY  → paper search and metadata"
echo "   EXA_API_KEY               → web search for related work"
echo "   PAPERBANANA_PATH          → path to PaperBanana executable"
echo ""
echo " Bootstrap files:"
echo "   CLAUDE.md       → Claude Code"
echo "   GEMINI.md       → Gemini / Antigravity"
echo "   AGENTS.md       → Codex, OpenClaw, OpenCode, Droid"
echo "   .cursor/rules/  → Cursor"
echo "   .windsurf/rules/ → Windsurf"
echo ""
echo " Next steps:"
echo "   1. Open this project in your agent"
echo "   2. Try: /paper-orchestra  or  /literature-review-agent"
echo "───────────────────────────────────────────────────"
echo ""
