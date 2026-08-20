# Contributing

Keep platform operations modular and explicit.

- Add new platform actions to the matching toolbox manifest before exposing them.
- Mark every action as `api` or `browser`; browser actions must remain `supervised_local_only`.
- Do not add secrets, browser profiles, tokens, downloaded media, or user data.
- Preserve the shared schemas or introduce a new schema version when a breaking change is necessary.
- Document OAuth scopes, required environment-variable names, rate-limit considerations, and whether an action writes external state.

Changes that publish, reply, follow, vote, or otherwise affect a third-party account must require application-level authorization at call time.
