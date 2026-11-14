# Branch ownership and collaboration

The project brief in [docs/project-brief.md](project-brief.md) defines the scope and team responsibilities. The team works on **four long-lived branches, one per person**. All changes reach `main` only through a reviewed pull request (PR).

| Owner | Working branch | Main area of work |
|---|---|---|
| Abdul Kareem — Backend Lead | `feature/api-incidents` | FastAPI API, Firebase Auth/Firestore, incident workflows, shared contracts, video/camera configuration and vision-worker integration |
| Hania — Backend and Computer Vision Engineer | `feature/person-zone-worker` | Person detection/tracking, zone rules, model thresholds and accuracy evaluation |
| Minal — Frontend Lead and UI Systems | `feature/monitoring-ui` | Next.js foundation, theme and responsive UI system, monitoring/camera screens |
| Musaykah — Frontend Engineer and Incident Workflows | `feature/incident-review-ui` | Incident list, filters, detail/evidence view and acknowledgement flow |

## Branch rules

- Use only these four working branches. Do not create extra branches for your own work; commit to your assigned branch.
- Never commit or push directly to `main`, and never force-push a shared branch.
- Work only on your own branch. To use a teammate's unmerged work, wait for it to reach `main`, or agree with them first.
- Do not commit secrets (`.env` files, keys), footage, sample videos or model weights. `.gitignore` blocks the common cases; check `git status` before committing.

## Daily workflow

1. **Start from the latest `main`:**
   ```bash
   git switch <your-branch>
   git fetch origin
   git merge --ff-only origin/main   # if this fails, use: git merge origin/main
   ```
2. **Keep changes focused.** Agree on API and event fields in `contracts/` with Abdul Kareem before integrating the frontend or the vision worker.
3. **Push your branch and open a PR into `main`.** Describe the change, how you checked it, and any open questions. Add screenshots for UI changes. Request at least one teammate's review.
4. **Address review feedback** on the same branch. The PR updates automatically when you push.
5. **Merge only after approval and passing checks** (Backend CI, Worker CI). Then bring your branch up to date with `main` again (step 1) before your next task.

Keep one open PR per branch at a time. If your previous PR is still under review, keep committing to the same branch; the new commits join that PR.

## Reviews

| Change touches | Reviewer |
|---|---|
| `contracts/`, API payloads or event fields | Abdul Kareem plus the affected owner (Hania for events; Minal or Musaykah for incident data) |
| `worker/` detection, tracking or rules | Hania |
| `worker/` video sources, publisher or API client | Abdul Kareem |
| Shared frontend components or design tokens | Minal and Musaykah |

## Protecting `main`

Repository administrators should enable a `main` branch ruleset that:

- requires a pull request with at least one approval;
- requires the CI checks to pass;
- blocks force pushes and deletion;
- disables bypass for collaborators.

A branch name alone does not prevent direct pushes; only the ruleset does.
