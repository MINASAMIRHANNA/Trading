# Environment Unification (single venv + shared systemd env)

Goal: run **Brain (8100) + Mina stacks (8000/8001/8002) + Gateway (8200)** using **one** Python virtualenv at the monorepo root, and a **single** shared environment file loaded by systemd.

## 1) One Python venv (root)

Create root venv (recommended) and install deps:

```bash
cd ~/projects/Trading
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip wheel setuptools
# install everything (brain + mina_bot + gateway)
python -m pip install -r services/brain/requirements.txt -r services/mina_bot/requirements.txt -r gateway/requirements.txt
```

Optional: freeze the exact installed versions for reproducibility:

```bash
python -m pip freeze > requirements.lock.txt
```

## 2) Prevent service-local venv from hijacking systemd

Mina_Bot runbooks previously activated `services/mina_bot/.venv`. We now:
- **prefer an already-activated venv** (from systemd), and
- allow overriding via `TRADING_VENV`.

See: `services/mina_bot/ops/_lib.sh`.

To enforce the policy on servers, you can also move/remove the local venv:

```bash
mv ~/projects/Trading/services/mina_bot/.venv ~/projects/Trading/services/mina_bot/.venv__disabled 2>/dev/null || true
```

## 3) Shared systemd environment

Copy examples:

```bash
cd ~/projects/Trading
cp ops/env/trading.env.example ops/env/trading.env
cp ops/env/trading.secrets.env.example ops/env/trading.secrets.env
# edit the two files
nano ops/env/trading.env
nano ops/env/trading.secrets.env
```

## 4) systemd unit template

Use `EnvironmentFile=` to load both env files, and always source the **root** venv.

Example (Gateway):

```ini
[Service]
WorkingDirectory=/home/mina/projects/Trading
EnvironmentFile=/home/mina/projects/Trading/ops/env/trading.env
EnvironmentFile=-/home/mina/projects/Trading/ops/env/trading.secrets.env
ExecStart=/bin/bash -lc 'source "${TRADING_VENV}/bin/activate" && python -m uvicorn gateway_api.main:app --host 0.0.0.0 --port ${GATEWAY_PORT}'
Restart=always
RestartSec=2
```

Example (Mina LIVE stack):

```ini
[Service]
WorkingDirectory=/home/mina/projects/Trading/services/mina_bot
EnvironmentFile=/home/mina/projects/Trading/ops/env/trading.env
EnvironmentFile=-/home/mina/projects/Trading/ops/env/trading.secrets.env
ExecStart=/bin/bash -lc 'source "${TRADING_VENV}/bin/activate" && bash ops/run_live_stack.sh'
Restart=always
RestartSec=2
```

Reload + restart:

```bash
sudo systemctl daemon-reload
sudo systemctl restart trading-gateway.service trading-mina-live.service trading-mina-paper.service trading-mina-pump.service
```

## 5) Validation

```bash
curl -sS http://127.0.0.1:8200/api/health/aggregate | head -c 900; echo
python -c "import sys; print(sys.executable); print(sys.version)"
which python
which uvicorn
```
