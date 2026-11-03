# Project setup: Scheme Saathi

Follow these steps on **Windows using PowerShell**. You will create your
own branch from `main`, then run the API and website on your computer.

> **Before starting:** PR #11 must be merged into `main` for the Phase 3
> application described here to be available there. Do not copy old files
> over the new code.

## 1. Install the basics

- **Git** to download the project and create your branch.
- **Python 3.12** (recommended; this is also the CI version). The project
  requires Python 3.11 or newer.
- **VS Code** or another editor.
- Access to the private GitHub repository. Ask the repository owner if
  GitHub says you cannot access it.

Check Python and Git in PowerShell:

```powershell
python --version
git --version
```

If either command is not found, install that tool and open a new terminal.
If `python` opens the Microsoft Store, use `py -3.12` instead of `python`
when creating the virtual environment below.

## 2. Download main and create your branch

Open PowerShell in the folder where you want to keep the project.

```powershell
git clone https://github.com/Roy-developer/scheme-saathi-capstone.git
Set-Location scheme-saathi-capstone
git switch main
git pull --ff-only origin main
git switch -c feature/your-name-your-task
```

Replace `feature/your-name-your-task` with your own branch name, for
example `feature/asha-document-checks`. Use a new name, not someone else's
branch.

**Already cloned the project?** Open its folder and skip `git clone`.
Run `git status` first. Save your existing work in its own branch before
switching branches; do not discard files just to follow this guide.
Then run the remaining commands above.

Check that you are on your branch:

```powershell
git branch --show-current
```

It should show your branch name, **not `main`**.

## 3. Create a Python environment and install the project

Run these commands from the project folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

The `.venv` folder holds this project's Python packages. Installation can
take a few minutes.

This guide calls the environment's Python directly, so you **do not need
to activate it or change PowerShell's execution policy**.

In VS Code, choose **Python: Select Interpreter** and select
`.venv\Scripts\python.exe`.

## 4. Add your local API keys

Create your local settings file:

```powershell
Copy-Item .env.example .env
```

Do this only if `.env` does not already exist. Keep your existing settings
if you have already configured them.

Open `.env` in your editor and replace the example values:

```dotenv
OPENROUTER_API_KEY=your_openrouter_chat_key_here
OPENROUTER_CHAT_MODEL=openai/gpt-4o-mini
OPENROUTER_API_KEY_FREE=your_openrouter_embedding_key_here
OPENROUTER_EMBEDDING_MODEL=voyageai/voyage-4
```

| Setting | Used for |
|---|---|
| `OPENROUTER_API_KEY` | Rewording search queries and understanding free-text interview replies |
| `OPENROUTER_API_KEY_FREE` | Search embeddings and hosted reranking |
| The two model settings | Which chat and embedding models to call |

Use authorized OpenRouter keys with access and credit for those models.
**The name `_FREE` does not mean requests are free.** Chat, embedding and
reranking requests may cost money. Never put actual keys in screenshots,
chat messages, source files, commits or pull requests. `.env` is ignored
by Git.

The API reads `.env` automatically. Restart the API after changing it.
Do not install or launch Qdrant separately: the pilot uses an in-memory
index. The API also launches its own MCP tool server.

## 5. Start the API

Keep this terminal open in the project folder:

```powershell
.\.venv\Scripts\python.exe -m uvicorn src.api.app:app --reload --host 127.0.0.1 --port 8000
```

Wait for the startup-complete message, then open:

- Health: <http://127.0.0.1:8000/health> — should show `{"status":"ok"}`.
- API documentation: <http://127.0.0.1:8000/docs>.

The API stores local conversation checkpoints under
`data\runtime\journey.sqlite3`. This is a local, Git-ignored file, not a
shared team database. Use made-up people and answers only.

## 6. Start the website

Open a **second PowerShell terminal** in the same project folder. Leave
the API running in the first terminal.

```powershell
$env:SCHEME_SAATHI_API_URL = "http://127.0.0.1:8000"
.\.venv\Scripts\python.exe -m streamlit run src\ui\app.py --server.address 127.0.0.1 --server.port 8501
```

Open <http://127.0.0.1:8501>.

The website calls the API on port `8000`. Both terminals must stay open.
Press **Ctrl+C** in each terminal when you want to stop the app.

## 7. Try the app

1. Search for `widow pension` or `PM-KISAN farmer support`.
2. Read the source passages returned by search.
3. Choose **Check all found schemes** for a shared interview, or
   **Continue to the synthetic eligibility demo** for one scheme.
4. Answer using made-up facts. Clear `yes`, `no`, `I don't know` and dates
   work without an answer-reading model call. Free-text replies may call
   the model and ask you to confirm its interpretation.
5. Read each scheme's result and the plan history.

Search itself makes external model calls. The first search may take
longer while the passage index is built. Search can miss relevant schemes;
it does not check every scheme in India. The current reviewed pilot has
only two schemes, and its eligibility results are **mock results**, not
government approvals.

## 8. Run the tests before changing code

From the project folder:

```powershell
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
```

The automated tests use fake model/network responses where needed; you do
not need live OpenRouter calls to run them. The API tests start a local MCP
process themselves.

You can stop the running app terminals before testing. If a test fails,
read the first failure before changing code or installing more packages.

## 9. Save your work on your branch

After making your changes, run the tests again, then inspect your files:

```powershell
git status
git diff
```

Stage only the files for your task. For example:

```powershell
git add path\to\your_changed_file.py
git commit -m "Describe your change"
git push -u origin feature/your-name-your-task
```

Replace the example path and branch name with yours. On GitHub, create a
pull request with **base: `main`** and **compare: your branch**. Do not
push your changes directly to `main`.

Running locally or pushing a branch is **not a deployment**. Azure access
is not needed for this guide.

## Common problems

| Problem | What to do |
|---|---|
| Private repository not found | Sign in to the correct GitHub account and check repository access. Do not put an access token in the clone URL. |
| `No module named ...` | Make sure installation finished and that you are using `.\.venv\Scripts\python.exe` from the project folder. |
| Website cannot reach the API | Check the first terminal for startup errors, open `/health`, and confirm the API URL in step 6. |
| Search fails or returns an authentication error | Check both keys in `.env`, model access and account credit; restart the API. Do not print the keys while debugging. |
| Free text is not understood | Answer directly with yes/no/a date. This is the safe fallback when interpretation is unavailable or uncertain. |
| Port `8000` or `8501` is already in use | Stop your own earlier app terminal with Ctrl+C. Do not stop another person's process. |
| You changed `.env` but behavior did not change | Stop and restart the API; do not rely on code reload to pick up environment-file edits. |

## Where to read next

- [Phase 1: shared rule engine](docs/PHASE1_CODE_WALKTHROUGH.md)
- [Phase 2: supervisor and interview](docs/PHASE2_CODE_WALKTHROUGH.md)
- [Phase 3: multi-scheme journey](docs/PHASE3_CODE_WALKTHROUGH.md)
- [Phase-wise plan](docs/PHASE_WISE_IMPLEMENTATION_PLAN.md)
