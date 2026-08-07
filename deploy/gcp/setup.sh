#!/usr/bin/env bash
# Bootstrap a Debian 12 VM to run the multi-agent Discord bot.
# Idempotent: safe to re-run after a failure or a partial setup.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/2001-Ankit/Multiagent.git}"
SITE_URL="${SITE_URL:-https://github.com/2001-Ankit/agenticblog.git}"
APP_DIR="$HOME/multi-agent"
SITE_DIR="$HOME/agenticblog"
TIMEZONE="${TIMEZONE:-Asia/Kathmandu}"

say() { printf '\n\033[1;36m==> %s\033[0m\n' "$1"; }

say "System packages"
sudo apt-get update -qq
# git for publishing, build tools because some wheels have no aarch64/slim build,
# fontconfig so Pillow can find system fonts if the bundled ones are ever missing.
sudo apt-get install -y -qq \
  git curl ca-certificates build-essential \
  python3 python3-venv python3-dev \
  fonts-dejavu-core fontconfig tzdata

say "Timezone -> $TIMEZONE"
sudo timedatectl set-timezone "$TIMEZONE"

# e2-micro has 1 GB of RAM and LangChain is not a small import. Swap turns an
# OOM kill into a slow moment, which is the difference between a bot that stays
# up and one that dies silently overnight.
if ! sudo swapon --show | grep -q '/swapfile'; then
  say "Adding 2 GB swap"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  # Prefer RAM; only reach for swap under real pressure.
  echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/99-swap.conf >/dev/null
  sudo sysctl -q -p /etc/sysctl.d/99-swap.conf
else
  say "Swap already configured"
fi

say "uv"
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"
grep -q '.local/bin' "$HOME/.bashrc" || \
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$HOME/.bashrc"

say "Application"
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi

say "Blog site (publishing target)"
# The site repo is usually private, and a credential prompt would hang a
# non-interactive run forever. Fail fast and carry on: everything except
# publishing still works, and the clone can be done by hand afterwards.
export GIT_TERMINAL_PROMPT=0
if [ -d "$SITE_DIR/.git" ]; then
  git -C "$SITE_DIR" pull --ff-only || echo "  (pull failed - check credentials)"
elif git clone "$SITE_URL" "$SITE_DIR" 2>/dev/null; then
  echo "  cloned"
else
  echo "  SKIPPED: $SITE_URL needs credentials."
  echo "  Clone it by hand once a PAT is configured:"
  echo "    git clone $SITE_URL $SITE_DIR"
  echo "  Publishing stays disabled until then; everything else works."
fi

say "Python dependencies"
cd "$APP_DIR"
uv sync

say "Checks"
uv run python -c "
from src.social_studio.render_slides import _font
from src.social_studio.export_video import ffmpeg_path
print('  fonts  :', _font('serif', 40).getname())
print('  ffmpeg :', ffmpeg_path())
"

say "systemd service"
sudo cp "$APP_DIR/deploy/gcp/multi-agent.service" /etc/systemd/system/multi-agent.service
sudo sed -i "s|__USER__|$USER|g; s|__APP_DIR__|$APP_DIR|g; s|__HOME__|$HOME|g" \
  /etc/systemd/system/multi-agent.service
sudo systemctl daemon-reload

cat <<EOF

Setup complete. Remaining steps, in order:

  1. Copy your .env to $APP_DIR/.env  then:  chmod 600 $APP_DIR/.env
  2. In it, set:  BLOG_SITE_DIR=$SITE_DIR
  3. Give git a push credential for the blog repo:
       git config --global user.name  "Your Name"
       git config --global user.email "you@example.com"
       git config --global credential.helper store
       cd $SITE_DIR && git push
  4. sudo systemctl enable --now multi-agent
  5. journalctl -u multi-agent -f

Stop the bot on your laptop first - two instances reply to every message twice.
EOF
