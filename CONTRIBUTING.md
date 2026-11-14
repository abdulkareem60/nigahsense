# Contributing to NigahSense

How the four of us work in this repository. Scope and roles: [project brief](docs/project-brief.md). What to build: [requirements](docs/requirements.md). How it fits together: [architecture](docs/architecture.md).

## Team, branches and ownership

Each person works on **one long-lived branch**. Do not create other branches for your work.

| Person | GitHub | Branch | Owns |
|---|---|---|---|
| Abdul Kareem, Backend Lead | `abdulkareem60` | `feature/api-incidents` | API, Firebase (Auth, Firestore, rules), shared contracts, video sources and event publisher in the worker, integration, backend review |
| Hania, Backend and Computer Vision | `HaniaImran576` | `feature/person-zone-worker` | Detector, tracker, zone and event rules, accuracy evaluation ([worker ownership table](worker/README.md#ownership-what-hania-can-take-over-next)) |
| Minal, Frontend Lead and UI Systems | `minalsajid25` | `feature/monitoring-ui` | Next.js structure, design system and themes, navigation, monitoring and camera screens, zone editing |
| Musaykah, Frontend Engineer and Incident Workflows | `musaykah8` (invitation pending) | `feature/incident-review-ui` | Incidents and evidence review, search, registered people, analytics, reports, camera-health views |

Shared files need agreement before you change them:

| Shared area | Change only with |
|---|---|
| [`contracts/`](contracts/README.md) (event and incident payloads) | Abdul Kareem plus the affected owner (Hania for events, Minal or Musaykah for incident data) |
| Shared frontend components and design tokens | Minal and Musaykah |
| Worker detection, tracking and rules | Hania |
| Worker video sources, publisher and API client; backend | Abdul Kareem |

## How changes reach `main`

`main` is protected by the repository ruleset **"Protect main"** (active, no bypass for anyone, admins included). It enforces:
- changes only through a **pull request with at least 1 approving review** (the author cannot approve their own PR);
- **no force pushes** and no deletion of `main`.

CI checks run on PRs but are **not yet a required status check** in the ruleset. Until an admin adds them, reviewers must not approve a PR with failing checks.

## Workflow

**1. Bring your branch up to date** before starting, and after any PR is merged:

```bash
git switch <your-branch>
git fetch origin
git merge origin/main
git push origin <your-branch>
```

Use `merge`, not `rebase`, on these shared long-lived branches, so you never need to force-push.

**2. Commit small, focused changes** with messages in the style already used: `feat(worker): …`, `fix(api): …`, `docs: …`, `ci: …`, `test: …`. Never commit:
- secrets (`.env` files, service-account keys, tokens);
- footage or sample videos;
- model weights;
- run output (`worker/runtime/`).

`.gitignore` blocks the common cases, but still check `git status` before every commit.

**3. Run the relevant tests locally.** Commands: [backend](README.md#test) and [worker](worker/README.md#tests).

**4. Open a PR into `main`** from your branch. Keep **one open PR per branch**; new commits pushed to the branch join that PR. The description should say:
- what changed and why;
- how you checked it, with the real results (test counts, evaluation numbers);
- screenshots for UI changes;
- open questions, and any contract change, called out explicitly.

Request a review from the owner of the area you touched.

**5. CI** runs automatically, depending on which files changed:

| Workflow | Runs when a PR touches | Jobs |
|---|---|---|
| Backend CI | `backend/`, `contracts/`, Firebase config files | Unit and API tests; Firestore emulator tests |
| Worker CI | `worker/`, `contracts/`, `backend/app/schemas/` | Worker tests (no model); tracking regression (Ultralytics, CPU) |

Both also run on every push to `main`. A PR that changes only docs (`docs/`, `*.md` outside those folders) triggers no CI; its review is the check.

**6. Review.** The reviewer runs or reads the checks, looks at the diff (including that no secrets or media are added), and approves or requests changes. Fix feedback on the same branch.

**7. Merge** after approval and green checks, using **"Create a merge commit"** (as PR #1 was). Squash merges rewrite your commits on `main`, which makes the next sync of a long-lived branch messy. Then sync your branch again (step 1).

## Keeping docs current

The docs are living documents. Update them in the same PR as the change they describe, so decisions and results keep their history in Git.

| When you… | Update |
|---|---|
| Change what a feature does or its status | [docs/requirements.md](docs/requirements.md) |
| Change components, data flow, storage, auth or retries | [docs/architecture.md](docs/architecture.md) |
| Change the detector, tracker, rules or clips, or measure accuracy | [docs/accuracy-evaluation.md](docs/accuracy-evaluation.md) (add result rows; never delete old ones) |
| Change an event or incident payload | [contracts/](contracts/README.md), in a reviewed contract PR |
| Change setup, commands or environment variables | [README.md](README.md) or [worker/README.md](worker/README.md) |
| Change team process | This file |

## Definition of done

A change is done when:
- it does what its [requirements](docs/requirements.md) entry says, and that entry's status is updated;
- tests covering it are added or updated, pass locally and pass in CI;
- detection or tracking changes have evaluation results recorded, and no existing clip got worse without an explained reason;
- contract changes are agreed and reviewed, and mock data matches them;
- UI changes work in light and dark mode at phone and desktop widths, and show detections as possible until reviewed;
- docs and `.env.example` files are updated;
- no secrets, footage or weights are committed;
- the PR is approved by at least one teammate and merged into `main`.
