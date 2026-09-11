# Private template access for CI runners

Owner: DevOps & Distribution Engineer. Resolves the scope §7 open item
"Decide access model (SSH key vs token) for private repo pulls from CI runners".
Decision recorded as D-025 (pending Lead ratification).

## Problem

The template lives in one private GitHub repo. Downstream projects generated
from it keep `.copier-answers.yml` and run `copier update` later, including from
their own CI. `copier update` clones the template repo at a tag, so every
downstream CI runner needs read access to this private repo. Developer laptops
use their normal GitHub SSH/HTTPS auth; the question is CI.

Options: SSH deploy key, fine-grained PAT, GitHub App installation token.

## Decision: GitHub App installation token (recommended), SSH deploy key as interim

Use a dedicated **GitHub App** owned by the org, installed on the template repo
and on each consumer repo, minting a short-lived installation token in CI.

Until the App is set up, a **read-only SSH deploy key** on the template repo is
sanctioned for a small number of consumer repos. Migrate to the App before the
consumer count grows past roughly five, or before the first repo owned by
another team.

### Why the App over the alternatives

| Criterion | SSH deploy key | Fine-grained PAT | GitHub App token |
| --- | --- | --- | --- |
| Identity | Per-repo keypair, no owner | A person's account | Org-owned, no person |
| Token lifetime | Permanent private key | Up to 1 year, then manual renew | Installation token expires in 1 hour, minted per run |
| Scope | The one repo the key is attached to | Selectable: this repo, Contents read | Selectable: this repo, Contents read |
| Rotation | Manual, per consumer repo | Manual, breaks on expiry / person offboarding | Rotate the App private key once, centrally; consumers unchanged |
| Blast radius if the CI secret leaks | Read of one repo, until someone notices and rotates everywhere | Whatever the PAT is scoped to, for up to a year | One hour of read to installed repos, then dead |
| Blast radius if the central secret leaks | n/a | n/a | App private key can mint tokens for all installed repos (mitigate: store in a secret manager, rotate on schedule) |
| Consumer setup | Paste private key secret | Paste token secret | One `create-github-app-token` step + App id / private key as org secrets |
| Audit | Appears as the deploy key | Appears as the person | Appears as the App, per-installation |

The App wins on the two things that matter at scale: rotation is central (no
fan-out to N consumer repos) and leaked CI secrets are ephemeral. The PAT ties
automation to a human account and expires; a "machine user" PAT is just a PAT
with worse ownership. The deploy key is fine for one or two repos but the
permanent private key copied into every consumer is exactly the fan-out the App
avoids.

## Owner checklist (copy-paste, tick through in order)

Everything below needs org-owner access this team does not have; nobody but the
owner can complete it. Steps 1-5 are one-time. Step 6 repeats per new consumer.

- [ ] 1. Create the GitHub App (`Setup: GitHub App` step 1-2 below). Note the App ID
      and download the private key `.pem`.
- [ ] 2. Install the App on the template repo (`microservice-boilerplate`) and on
      every consumer repo that will run `copier update` / `msvc-gen update` in CI
      (`Setup: GitHub App` step 3).
- [ ] 3. Add org secrets `TEMPLATE_APP_ID` and `TEMPLATE_APP_PRIVATE_KEY` (step 4),
      scoped to the consumer repos.
- [ ] 4. Put the `Mint template read token` + `copier update` / `msvc-gen update`
      steps below into each consumer repo's update workflow, replacing
      `$TEMPLATE_REF` with that repo's pinned tag (D-012: never left unset).
- [ ] 5. Put a rotation reminder on the calendar (step 5): regenerate
      `TEMPLATE_APP_PRIVATE_KEY` on a fixed schedule, e.g. every 90 days.
- [ ] 6. For each new consumer repo: add it to the App's installation (step 3) and
      give it the two org secrets (already scoped) - no new App, no new key.

## Setup: GitHub App

One-time, by an org owner:

1. Org **Settings -> Developer settings -> GitHub Apps -> New GitHub App**.
   - Name: `microservice-template-reader`.
   - Homepage URL: the template repo URL.
   - Uncheck **Webhook -> Active**.
   - **Repository permissions -> Contents: Read-only**. Nothing else.
   - **Metadata: Read-only** (implied).
   - "Where can this GitHub App be installed?" -> **Only on this account**.
2. Create the App. On its page: **Generate a private key**, download the `.pem`.
   Note the **App ID**.
3. **Install App** -> this account -> **Only select repositories** -> pick the
   template repo and every consumer repo that runs `copier update` in CI. Add
   repos here as new consumers appear.
4. Store as **organization** secrets (or repo secrets if org secrets are not
   available): `TEMPLATE_APP_ID`, `TEMPLATE_APP_PRIVATE_KEY` (the full `.pem`
   contents). Restrict the org secret to the consumer repos.
5. Rotate `TEMPLATE_APP_PRIVATE_KEY` on a schedule (for example every 90 days):
   generate a new key on the App page, update the secret, delete the old key.
   No consumer repo change needed.

In each consumer repo's `copier update` workflow (`$TEMPLATE_REF` is that repo's
pinned template tag, e.g. `v0.3.0` - set it as a repo variable or hardcode it;
never left unset, D-012):

```yaml
      - name: Mint template read token
        id: tmpl
        uses: actions/create-github-app-token@v1
        with:
          app-id: ${{ secrets.TEMPLATE_APP_ID }}
          private-key: ${{ secrets.TEMPLATE_APP_PRIVATE_KEY }}
          owner: ${{ github.repository_owner }}
          repositories: "microservice-boilerplate"   # the template repo name

      - uses: actions/checkout@v4                     # checks out the consumer repo

      - name: msvc-gen update
        env:
          GH_TOKEN: ${{ steps.tmpl.outputs.token }}
          TEMPLATE_REF: v0.3.0    # this repo's pinned template tag - update deliberately
        run: |
          git config --global url."https://x-access-token:${GH_TOKEN}@github.com/".insteadOf "https://github.com/"
          uv tool install msvc-gen   # or: pipx install msvc-gen
          msvc-gen update -o . --vcs-ref "$TEMPLATE_REF"
```

`--vcs-ref` is always explicit (D-012). The `insteadOf` rewrite lets Copier's
HTTPS clone of the template use the installation token without embedding it in
`.copier-answers.yml` (Copier stores `_src_path`; keep it as the plain HTTPS URL).

`msvc-gen update` is the shipped CLI (a thin wrapper over `copier.run_update`,
`msvc_gen/cli.py`) and is what the owner's install docs point consumers at; raw
`copier update --vcs-ref "$TEMPLATE_REF" --defaults --trust` works identically
if a consumer prefers calling Copier directly.

## Setup: SSH deploy key (interim only)

By a template-repo admin:

1. `ssh-keygen -t ed25519 -N "" -f template_deploy_key -C "copier-update ci"`
2. Template repo **Settings -> Deploy keys -> Add deploy key**: paste
   `template_deploy_key.pub`, leave **Allow write access** unchecked.
3. In each consumer repo, add secret `TEMPLATE_DEPLOY_KEY` = contents of the
   private `template_deploy_key`.
4. Consumer workflow:

   ```yaml
         - uses: webfactory/ssh-agent@v0.9.0
           with:
             ssh-private-key: ${{ secrets.TEMPLATE_DEPLOY_KEY }}
         - run: copier update --vcs-ref "$TEMPLATE_REF" --defaults
   ```

   `.copier-answers.yml` `_src_path` must be the `git@github.com:org/repo.git`
   SSH form for this to work.
5. Rotate by generating a new key, replacing the deploy key, and updating the
   secret in every consumer repo. This per-consumer fan-out is the reason to
   move to the App.

## Not chosen

- Fine-grained PAT on a machine user: ties access to an account, expires within
  a year, same secret-fan-out problem as the deploy key with worse ownership.
- Making the template repo public: out of scope; scope §7 mandates private.
- Vendoring the template into each consumer: defeats `copier update`.
