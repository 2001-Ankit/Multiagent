# Deploying the bot on Google Cloud

## Why Compute Engine and not Cloud Run

Cloud Run is the obvious-looking choice and it is the wrong one here.

The Discord bot holds a **persistent websocket** to Discord's gateway. Cloud Run is
request-driven and scales to zero; keeping a gateway connection alive there means
`min-instances=1` with CPU always allocated, which costs more than a VM and still
gives you an **ephemeral filesystem** — so `data/blog/`, `data/social/` and the
cloned site repo would vanish on every restart. The in-process briefing scheduler
also needs the process to simply stay running.

A small always-on VM is the correct shape for this workload.

## Which machine, and the thing to watch about credits

**Your $300 trial credits expire after 90 days.** The GCP *free tier* does not.
So size the VM to land inside the free tier and treat the credits as headroom:

| | e2-micro | e2-small |
|---|---|---|
| RAM | 1 GB | 2 GB |
| Cost | **free tier** (1/month, `us-central1`, `us-west1` or `us-east1`) | ~$13/month |

LangChain plus Pillow is a tight fit in 1 GB. Start on **e2-micro with swap** (the
setup script adds 2 GB). If it gets OOM-killed under load, resize to e2-small —
your credits cover that for well over a year, but it will start billing when they
run out, so decide deliberately.

Region must be `us-central1`, `us-west1` or `us-east1` for the free tier. Latency
from Nepal is irrelevant here: nothing is user-facing, the bot dials out to Discord.

## Steps

### 1. Create the VM

```bash
gcloud compute instances create multi-agent \
  --zone=us-central1-a \
  --machine-type=e2-micro \
  --image-family=debian-12 \
  --image-project=debian-cloud \
  --boot-disk-size=30GB \
  --boot-disk-type=pd-standard
```

30 GB standard persistent disk is the free-tier limit. Do not use `pd-balanced`
— it is not free-tier eligible.

### 2. Connect and run the bootstrap

```bash
gcloud compute ssh multi-agent --zone=us-central1-a
```

Then on the VM:

```bash
curl -fsSL https://raw.githubusercontent.com/2001-Ankit/Multiagent/main/deploy/gcp/setup.sh -o setup.sh
less setup.sh          # read it before running it
bash setup.sh
```

The script is idempotent — safe to re-run after a failure.

### 3. Secrets

Copy your `.env` up. Never commit it, and never paste tokens into a chat:

```bash
gcloud compute scp .env multi-agent:~/multi-agent/.env --zone=us-central1-a
```

Then lock it down on the VM:

```bash
chmod 600 ~/multi-agent/.env
```

Set `BLOG_SITE_DIR=/home/YOUR_USER/agenticblog` in it — the default `blog-site`
is a relative path that only exists on your laptop.

### 4. Let the VM push to the blog repo

Publishing commits and pushes, so the VM needs its own credentials. Use a
**fine-grained PAT scoped to the blog repo only** (Contents: read/write):

```bash
git config --global user.name  "Ankit Rai"
git config --global user.email "you@example.com"
git config --global credential.helper store
cd ~/agenticblog && git push        # enter the PAT once; it is cached after
```

A PAT scoped to one repo limits the blast radius if the VM is ever compromised.

### 5. Start it

```bash
sudo systemctl enable --now multi-agent
sudo systemctl status multi-agent
journalctl -u multi-agent -f          # live logs
```

## Important: stop your local bot

The bot refuses to start twice on one machine, but that lock is per-machine — it
cannot see the VM. **Two bots on two machines will both reply to every message.**
That is the duplicate-reply bug from before. Once the VM is running, stop the
local one.

## Operating it

```bash
sudo systemctl restart multi-agent    # after a config change
journalctl -u multi-agent -n 100      # recent logs
cd ~/multi-agent && git pull && sudo systemctl restart multi-agent   # deploy an update
```

`Restart=always` brings it back after a crash or a VM reboot.

## Cost control

Set a budget alert before you forget — this is the step people skip and regret:

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT_ID \
  --display-name="multi-agent" \
  --budget-amount=10USD \
  --threshold-rule=percent=50 --threshold-rule=percent=100
```

Egress is the other thing to watch. The free tier includes 1 GB/month of North
America egress; pushing images and video to GitHub counts against it. At your
volume this is nothing, but a runaway loop uploading video would not be.
