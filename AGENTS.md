<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

## Access Deserts architecture
**`CLAUDE.md` is the source of truth** for architecture, data sources, method and phases. In short:
- The data pipeline is Python (`/pipeline`), run by GitHub Actions. It writes static run files to `public/data/runs/{run_id}/` and never overwrites a run.
- The frontend reads only files under `public/data/`. It never calls external data sources.
- Source and parameter configuration lives in `pipeline/config/*.yaml`, not in database rows. Adding a city is configuration, not code.
- The Lovable Cloud tables, `/admin` and the Supabase integration are kept for now but new code must not depend on them (see "To retire later" in `CLAUDE.md`).
- `.lovable/plan/access-deserts-phased-implementation-plan-2026-10-04.md` is **superseded** by `CLAUDE.md`.
