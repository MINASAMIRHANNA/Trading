# GitHub Setup (Trading Monorepo)

## 1) Create a repo on GitHub
- Create a new repo named **Trading** (Private recommended).
- Do NOT initialize with README.

## 2) Initialize + push from your Mac
Run inside `~/projects/Trading`:

```bash
git init
git add .
git commit -m "chore: initial monorepo"

# SSH (recommended)
git remote add origin git@github.com:<YOUR_USERNAME>/Trading.git

git branch -M main
git push -u origin main
```

## 3) Daily workflow
- Create a branch per phase or feature:

```bash
git checkout -b phase-1-contracts
```

- Commit often:

```bash
git add -A
git commit -m "phase1: contracts v1"
```

- Push and open a Pull Request:

```bash
git push -u origin phase-1-contracts
```

## 4) What NOT to commit
Keep secrets and runtime artifacts out of git:
- `.env`, API keys
- `node_modules/`, `.venv/`
- `*.db`, `logs/`, large generated artifacts

Tip: if you ever need to version large model files, use Git LFS.
