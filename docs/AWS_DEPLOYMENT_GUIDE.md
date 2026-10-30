# Deploying Legal Workspace on AWS — a beginner's step-by-step guide

You do not need to know AWS. This guide uses **one** AWS service for the application: a single virtual server (called **EC2**). Everything else (database, API, UI, AI models, HTTPS) runs on that server inside Docker containers, started by one script, `deploy/deploy.sh`.

> **Read this first — what is and is not verified**
> * I validated the deployment files with `docker compose config` and `bash -n` (syntax). I **could not** run Docker containers, AWS, or GPUs in my build environment, so **nobody has run this deployment end to end yet**. Expect to fix a small thing or two on your first run. Part 9 lists the likely ones; if you get stuck, paste the error output to me.
> * Prices below are **rough, from memory**. Check the [AWS pricing page](https://aws.amazon.com/ec2/pricing/on-demand/) before you click "Launch".
> * This is a **single-server pilot**, not a highly available production system (see Part 10).

---

## Part 1 — What you are building, and what it costs

```
 your browser ──HTTPS──►  EC2 server (Ubuntu, one machine)
                           ├─ Caddy      web entrance, free HTTPS certificate
                           ├─ ui         the web app (nginx)
                           ├─ api        FastAPI backend
                           ├─ worker     reads uploaded files in the background
                           ├─ db         PostgreSQL + pgvector (all case data)
                           └─ ollama     runs the open-source AI models (qwen3, bge-m3)
```

**No SQS, no S3, no RDS, no Lambda.** (Your blueprint planned some of these; this version replaces the queue with PostgreSQL, file storage with the server's disk, and managed GPUs with this one machine.) Fewer parts means fewer things to learn and to pay for.

### Choose your path

| | Path A — "Learn deployment" (start here) | Path B — "Real AI models" |
| --- | --- | --- |
| Server | `t3.large` (2 vCPU, 8 GB RAM) | `g5.xlarge` (4 vCPU, 16 GB RAM, 24 GB GPU) recommended; `g4dn.xlarge` (16 GB GPU) is cheaper but tighter |
| AI | none: demo mode (only knows the built-in sample matter) | `qwen3:8b`, `qwen3:4b`, `bge-m3` running on the GPU |
| Disk | 30 GB | 100 GB |
| Rough cost (on-demand) | ≈ **US$0.09/hour** ≈ $60/month if left on | g5.xlarge ≈ **$1.0/hour** ≈ $735/month if left on 24×7 (g4dn.xlarge ≈ $0.53/hour) |
| Extra setup | none | request a GPU quota first (Part 2.5) |

**Recommendation:** do **Path A first** (cheap, you learn every step, and you can show the UI). Then, on the same guide, repeat Part 3 with a GPU server for Path B. **Stop the server when you're not using it** (Part 7.5) — a GPU server left on for a month is the most common surprise bill.

Other costs: disk (EBS) ≈ $0.08 per GB-month (100 GB ≈ $8), a public IPv4 address ≈ $0.005/hour (≈ $3.6/month), data transfer is negligible for a pilot. A CPU-only server can run the real models, but I expect document ingestion to be very slow (I have not measured it); use CPU only for a functional test with `LLM_MAIN_MODEL=qwen3:4b`.

---

## Part 2 — Prepare your AWS account (about 20 minutes)

**2.1 Create the account** at <https://aws.amazon.com> (needs a card). Sign in as the "root user".

**2.2 Protect it.** Console → click your account name (top right) → **Security credentials** → **Assign MFA device** → follow the steps with an authenticator app. *Do this before anything else; a stolen AWS login can run up huge bills.*

**2.3 Set a spending alarm.** Console search bar → type **Budgets** → **Create budget** → *Use a template* → **Monthly cost budget** → amount e.g. **50 USD** (Path A) or **300 USD** (Path B) → enter your email → Create. You will get an email when you approach the amount. (It warns; it does not stop spending.)

**2.4 Pick a region** (top-right dropdown). Choose the one nearest to your users, e.g. **Asia Pacific (Mumbai) `ap-south-1`**, or **US East (N. Virginia) `us-east-1`** which usually has the most instance types and the lowest prices. Use the **same region for everything** in this guide.

**2.5 Path B only — request GPU quota.** New accounts normally have a limit of **0** for GPU ("G") instances, so launching one fails with *"You have requested more vCPU capacity than your current vCPU limit"*. Fix it **now** because approval can take hours to a day or two:
Console → **Service Quotas** → **AWS services** → **Amazon Elastic Compute Cloud (Amazon EC2)** → search **Running On-Demand G and VT instances** → **Request increase at account level** → new value **4** (a g5.xlarge uses 4 vCPUs) → Request.

---

## Part 3 — Launch the server (about 10 minutes)

Console → search **EC2** → **Instances** → **Launch instances**, then fill in:

1. **Name:** `legal-workspace`
2. **Application and OS Images (AMI):**
   * Path A: choose **Ubuntu** → *Ubuntu Server 24.04 LTS*.
   * Path B: click **Browse more AMIs**, search **Deep Learning Base OSS Nvidia Driver GPU AMI (Ubuntu)** and pick the newest Ubuntu one. It comes with the NVIDIA GPU driver already installed (the part that is painful to install by hand).
3. **Instance type:** Path A `t3.large`; Path B `g5.xlarge`.
4. **Key pair (login):** **Create new key pair** → name `legal-workspace-key`, type **ED25519**, format **.pem** → Create. A file downloads — **keep it safe; AWS never shows it again** and anyone with it can log in to your server.
5. **Network settings → Edit:** create a new security group (this is the firewall) with exactly these rules:

   | Type | Port | Source | Why |
   | --- | --- | --- | --- |
   | SSH | 22 | **My IP** | so only you can log in (see note below about GitHub Actions) |
   | HTTP | 80 | Anywhere | needed to get the free HTTPS certificate |
   | HTTPS | 443 | Anywhere | the application |

   **Do not open any other port** (not 5432 database, not 8000, not 11434 Ollama).
6. **Configure storage:** Path A **30 GiB**; Path B **100 GiB**; type **gp3**; under *Advanced* set **Encrypted: Yes** (your documents are confidential).
7. Click **Launch instance**. Wait until **Instance state = Running** and **Status check = 2/2 passed**.

**3.1 Give the server a permanent address (Elastic IP).** Without this, the address changes every time you stop/start the server.
EC2 → left menu **Elastic IPs** → **Allocate Elastic IP address** → Allocate → select it → **Actions → Associate Elastic IP address** → choose your instance → Associate. Write down this IP, e.g. `3.110.20.5`.

**3.2 Choose the website name (`PUBLIC_HOST`).**
* **Best:** a domain you own (e.g. `legal.yourfirm.com`). Create an **A record** pointing at the Elastic IP at your domain registrar (or Route 53). It can take minutes to hours to take effect.
* **No domain? For a quick pilot:** use `3-110-20-5.sslip.io` (your IP with dashes + `.sslip.io`). It is a free third-party service that points that name at that IP, so the free HTTPS certificate still works. Fine for testing; use a real domain for anything serious.

---

## Part 4 — Connect and install Docker (about 10 minutes)

**4.1 Log in over SSH.**

*Windows (PowerShell):* first make the key file private, then connect.
```powershell
cd $HOME\Downloads
icacls .\legal-workspace-key.pem /inheritance:r /grant:r "$($env:USERNAME):R"
ssh -i .\legal-workspace-key.pem ubuntu@3.110.20.5
```
*Mac/Linux:* `chmod 400 ~/Downloads/legal-workspace-key.pem && ssh -i ~/Downloads/legal-workspace-key.pem ubuntu@3.110.20.5`

Type `yes` to the fingerprint question. You should see a prompt like `ubuntu@ip-172-31-...:~$`. Everything below is typed **on the server**.

**4.2 Install Docker** (skip if `docker --version` already works on your GPU AMI):
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit            # log out, then SSH in again so the group change applies
```
Check: `docker --version` and `docker compose version` (needs Compose **2.24 or newer**; the command above installs the latest).

**4.3 Path B only — check the GPU is visible:**
```bash
nvidia-smi                                          # should list your GPU (e.g. NVIDIA A10G, 24 GB)
docker run --rm --gpus all ubuntu nvidia-smi        # should print the same table from inside a container
```
If the second command fails with "could not select device driver", the NVIDIA Container Toolkit is missing: follow NVIDIA's install guide ("Installing the NVIDIA Container Toolkit"), then `sudo systemctl restart docker`.

---

## Part 5 — Get the code and configure it (about 10 minutes)

**5.1 Let the server read your private GitHub repo** (a read-only "deploy key"):
```bash
ssh-keygen -t ed25519 -f ~/.ssh/github_deploy -N "" -C legal-workspace-server
cat ~/.ssh/github_deploy.pub                        # copy this whole line
```
In your browser: GitHub → repo **pavan-kodati/rag-learning** → **Settings → Deploy keys → Add deploy key** → Title `aws-server`, paste the line, leave **Allow write access unticked** → Add key. Then on the server:
```bash
printf 'Host github.com\n  IdentityFile ~/.ssh/github_deploy\n  IdentitiesOnly yes\n' >> ~/.ssh/config
ssh-keyscan github.com >> ~/.ssh/known_hosts
```

**5.2 Download the code** to `/opt/legal-workspace`:
```bash
sudo mkdir -p /opt/legal-workspace && sudo chown $USER /opt/legal-workspace
git clone -b legal-workspace-v1 git@github.com:pavan-kodati/rag-learning.git /opt/legal-workspace
cd /opt/legal-workspace
```
(`legal-workspace-v1` is the branch where the code currently lives. After you merge it into `main` on GitHub, use `main` here and in Part 7.)

**5.3 Create your settings file.**
```bash
cp deploy/.env.prod.example deploy/.env.prod
# fill in random passwords (letters+digits only):
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 24)/; s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" deploy/.env.prod
nano deploy/.env.prod
```
In `nano` set:
* `PUBLIC_HOST=` your domain or `3-110-20-5.sslip.io`
* `AUTH_USERS=` your login(s) as `name:password:role`, comma separated (roles: `viewer` < `analyst` < `admin`). Example: `pavan:Some-Long-Passw0rd:admin`. **Use only letters, digits, `-` and `_` in passwords.**
* **Path A:** set `LLM_PROVIDER=fixture` and `EMBEDDER=hashing` (demo mode, no AI download).
* **Path B:** leave `ollama` for both. On a GPU with 16 GB (g4dn) change `LLM_MAIN_MODEL=qwen3:4b`.

Save: `Ctrl+O`, Enter, `Ctrl+X`.

> ⚠ Set `POSTGRES_PASSWORD` **before the first start**. The database fixes its password on first start; changing the file later does not change it.

---

## Part 6 — Start it (about 15–40 minutes, mostly downloads)

```bash
cd /opt/legal-workspace
deploy/deploy.sh up                 # builds the images and starts everything (first time: several minutes)
deploy/deploy.sh status             # services "running"; health shows {"status":"ok",...}
                                    # (Path B: "degraded" is normal until the models are downloaded, next step)
```
**Path B only:** download the AI models (≈ 9 GB, once):
```bash
deploy/deploy.sh pull-models
deploy/deploy.sh status             # health should now say "status":"ok" with the language model and embedder ok
```
**Path A only:** load the sample matter so there is something to click:
```bash
deploy/deploy.sh load-demo
```
Now open **https://YOUR-PUBLIC_HOST** in your browser (the first load may take ~30 seconds while Caddy obtains the certificate). Log in with the `AUTH_USERS` you set.
* Path A: open the matter *Vardhan Infotech v Kestrel* and click around (Gist, What changed, Directions, Ask, Hearing brief).
* Path B: create a matter and upload the PDFs from `data/synthetic/M2/batch1/` (on your laptop copy of the repo), commit the batch, then watch the progress; compare with `docs/screenshots/`.

The API's interactive documentation is at `https://YOUR-PUBLIC_HOST/api/docs`.

---

## Part 7 — Running it day to day

| Task | Command (on the server, in `/opt/legal-workspace`) |
| --- | --- |
| See status and health | `deploy/deploy.sh status` |
| Watch logs (all, or one service) | `deploy/deploy.sh logs` · `deploy/deploy.sh logs worker` |
| Deploy new code | `deploy/deploy.sh update legal-workspace-v1` (or `main`). Database changes apply automatically; takes a few minutes |
| Roll back | `deploy/deploy.sh update <older-commit-id>` (find ids with `git log --oneline`) |
| Change settings | edit `deploy/.env.prod`, then `deploy/deploy.sh up` |
| Stop everything (data is kept) | `deploy/deploy.sh down` |

**7.1 Backups** (do this before you put real documents in):
```bash
deploy/deploy.sh backup ~/backups          # database dump + uploaded files; keeps 14 days
```
Schedule it nightly: `crontab -e`, add `15 2 * * * /opt/legal-workspace/deploy/deploy.sh backup /home/ubuntu/backups`. Copy backups **off the server** regularly (e.g. `scp` to your laptop, or `aws s3 cp` to an S3 bucket) — a backup on the same disk dies with the disk. *I have not tested restoring; practise it once on a spare server before relying on it.*

**7.2 Disk space:** `df -h /` ; Docker images and model files are the big items. `docker system prune -f` removes unused images.

**7.3 Metrics:** `docker compose exec api curl -s localhost:8000/metrics` (Prometheus text; deliberately not reachable from the internet).

**7.4 Server health alarm (recommended):** EC2 → your instance → **Status checks → Create status check alarm** → notify your email if checks fail.

**7.5 Saving money — stop the server when idle:** EC2 → Instances → select → **Instance state → Stop instance**. You then pay only for disk and the IP, not the computer. **Start instance** brings it back with the same IP; the containers restart by themselves. (Models take a minute to load on the first question.) *Stop ≠ Terminate: "Terminate" deletes the server and its disk.*

---

## Part 8 — GitHub Actions: do you need it? (optional)

**No.** Parts 1–7 are a complete deployment, and typing `deploy/deploy.sh update` over SSH is perfectly fine for a pilot. Add automation only when you deploy often.

What you already have:
* **CI** (`.github/workflows/ci.yml`) — runs automatically on every pull request and on `main`: lint, type checks, all tests, UI tests, and builds the images. It needs **no setup** and no AWS access. Turning it on = merging the branch to `main`.
* **Deploy workflow** (`.github/workflows/cd.yml`) — manual button: SSH to your server and run `deploy/deploy.sh update <branch/tag/commit>`. Rolling back = run it again with an older commit. Nothing is deployed unless you click it.

**Setup (one time, ~15 minutes):**

1. **Open SSH to the internet.** GitHub's machines have changing IP addresses, so the security group rule for port 22 must become **Anywhere (0.0.0.0/0)**. This is safe **only because** password login is off on Ubuntu EC2 and your key is required — but it does expose SSH to scanners. Accept this trade-off, or skip Actions. (Safer advanced alternative: AWS Systems Manager — not covered here.)
2. **Create a dedicated key for GitHub** (on the server):
   ```bash
   ssh-keygen -t ed25519 -f ~/gha_key -N "" -C github-actions
   cat ~/gha_key.pub >> ~/.ssh/authorized_keys
   cat ~/gha_key                      # copy EVERYTHING printed, including the BEGIN/END lines
   ```
3. **Store three secrets** in GitHub: repo → **Settings → Secrets and variables → Actions → New repository secret**:
   * `DEPLOY_HOST` = your Elastic IP (e.g. `3.110.20.5`)
   * `DEPLOY_USER` = `ubuntu`
   * `DEPLOY_SSH_KEY` = the private key you copied
   Then remove the key files from the server: `shred -u ~/gha_key ~/gha_key.pub`.
4. **Optional approval gate:** repo → **Settings → Environments → New environment** → name it `production` → tick **Required reviewers** → add yourself. Every deploy then waits for your click.
5. **Run it:** repo → **Actions → "Deploy to server (manual)" → Run workflow** → enter the branch/commit (e.g. `main`) → Run. It prints the health check at the end.

> Note: this workflow **builds on the server** (no container registry needed, nothing extra to pay for). The CI "images" job that pushes images to GitHub's registry is optional and unused by this guide.

---

## Part 9 — Troubleshooting

| Symptom | Likely cause → fix |
| --- | --- |
| Can't SSH: "Connection timed out" | your home IP changed → EC2 → Security groups → edit the SSH rule → **My IP** |
| SSH: "UNPROTECTED PRIVATE KEY FILE" / "Permission denied (publickey)" | key file permissions (Windows: the `icacls` line) or wrong user name (`ubuntu`) |
| `docker: permission denied` | log out and SSH in again after `usermod -aG docker` |
| `up` fails: "unknown or invalid flag/!reset" | Docker Compose older than 2.24 → reinstall Docker with the `get.docker.com` command |
| `up` fails: "could not select device driver … gpu" | NVIDIA Container Toolkit missing (Part 4.3); fix it, then run `deploy/deploy.sh up` again |
| Instance won't launch: "vCPU limit" | GPU quota not approved yet (Part 2.5) |
| Browser: certificate error / site won't load | DNS not pointing at the Elastic IP yet (`nslookup YOUR_HOST`), or ports 80/443 not open in the security group; check `deploy/deploy.sh logs proxy` |
| `status` shows the language model "not reachable" | models not downloaded (`deploy/deploy.sh pull-models`), or Ollama still starting; `deploy/deploy.sh logs ollama` |
| Uploads stay "queued" | the worker is not running → `deploy/deploy.sh logs worker`; check disk space |
| Uploads fail with a model error | model too big for memory → set `LLM_MAIN_MODEL=qwen3:4b`, run `deploy/deploy.sh up` |
| `load-demo` refuses | it only works with `LLM_PROVIDER=fixture` and `EMBEDDER=hashing` (Path A) |
| Login rejected | `AUTH_USERS` format is `name:password:role`; after editing run `deploy/deploy.sh up` |
| Anything else | `deploy/deploy.sh logs` and send me the last 50 lines of the failing service |

---

## Part 10 — Security, limits, and clean-up

**Security checklist for this pilot**
- [x] Auth on (`AUTH_ENABLED=true` is forced by the production overlay), strong passwords, MFA on AWS root
- [x] Only ports 80/443 public; database and Ollama are not reachable from outside (the overlay removes their host ports)
- [x] Disk encrypted (you ticked *Encrypted*), HTTPS everywhere, no document text leaves the server (no external AI service)
- [ ] Restrict SSH to your IP (unless you chose GitHub Actions) — and consider turning off the Actions workflow when not in use
- [ ] Keep the OS updated: `sudo apt update && sudo apt upgrade -y` monthly, then reboot
- [ ] Off-server backups, tested restore
- [ ] Before real client data: a lawyer/security review. The legal corpus bundled with the app is an **UNVERIFIED** paraphrased seed.

**Known limits of this setup:** one server = one point of failure, no automatic failover, ~minutes of downtime during `update`; no multi-tenant isolation or single sign-on; the in-app rate limiter is per process; model quality and speed on your hardware are **unmeasured** — run `lw-eval` (see `docs/TESTING.md`) before trusting results.

**When you outgrow it** (more users, uptime requirements): move the database to **Amazon RDS for PostgreSQL** (it supports the pgvector extension — check the version supports 0.8), run the app on **ECS** or Kubernetes (`deploy/k8s/legal-workspace.yaml` is an outline), and put files in **S3** — which needs a small storage adapter that is **not written yet** (see `docs/DEPLOYMENT_PLAN.md`, "Known gaps").

**Clean-up — stop all charges** (when you're completely done):
1. EC2 → Instances → select → **Instance state → Terminate** (deletes the server and its disk — back up first!).
2. EC2 → **Elastic IPs** → select → **Actions → Release Elastic IP addresses** (an unattached IP still costs money).
3. EC2 → **Volumes**: delete any "available" volume left behind; **Snapshots**: delete any you made.
4. Check **Billing → Bills** the next day to confirm the charges stopped.
