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
- City-specific behaviour lives in `cities`/`sources` rows; pipeline code is generic per protocol adapter — so adding a city is configuration, not code.
- External data is fetched only in server functions/server routes (never edge functions, never the browser) — sources are plain http and block CORS.
- Admin actions check an httpOnly cookie derived from the `ADMIN_KEY` secret on every server call; writes use the service-role client, public tables are read-only to anon.
- Pipeline results are stored per `run_id` and never overwritten — snapshots must be reproducible.
