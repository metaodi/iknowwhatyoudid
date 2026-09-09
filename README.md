# iknowwhatyoudid
A local tool to get information about how you spend your days

## Development

This project follows Spec-Driven Development. Requirements and feature
specifications live under [`specs/`](specs/README.md); project-wide
principles and constraints live in
[`.specify/memory/constitution.md`](.specify/memory/constitution.md).

Install `specify`:

```
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git
```


Then use the following loop to create a new feature:

```
/speckit-specify <new feature in natural langauge>   # describe a new feature
/speckit-clarify                                     # optional, let the AI ask clarifying questions
/speckit.plan                                        # plan the implementation
/speckit-tasks                                       # optional, mostly to break down the plan in smaller chunks
/speckit-implement                                   # actually implement the feature
```