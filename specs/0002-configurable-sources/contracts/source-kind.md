# Contract: The source-kind boundary

This is the extension point (FR-026 to FR-032). It is written **as though it were public** — complete
enough that a kind supplied from outside this project would need nothing further — while the registry
that consumes it loads only kinds from inside this project (FR-031). That combination is the user's
decision on Q1: keep third-party code out of a process holding mail credentials, without designing a
boundary that would have to change to let it in later.

## The declaration

```python
class SettingType(StrEnum):
    STRING = "string"
    BOOL = "bool"
    INTEGER = "integer"
    DATETIME = "datetime"
    STRING_LIST = "string_list"
    PATH_LIST = "path_list"          # expanded (~, globs) and existence-checked
    IDENTITY_LIST = "identity_list"  # normalised for comparison

@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str                    # dotted path within the source block
    type: SettingType
    required: bool = False
    default: object | None = None
    help: str = ""              # user-facing; printed by `sources kinds`

class ReadingAvailability(StrEnum):
    AVAILABLE = "available"
    NOT_YET_IMPLEMENTED = "not_yet_implemented"

@dataclass(frozen=True, slots=True)
class SourceKind:
    name: str                              # dotted, stable, appears in users' files
    summary: str
    settings: tuple[SettingSpec, ...]
    credential_required: bool = False
    required_access: tuple[str, ...] = ()  # scope statements shown before granting (FR-025)
    destinations: tuple[str, ...] = ()     # every destination this kind may contact (FR-045)
    reading: ReadingAvailability = ReadingAvailability.NOT_YET_IMPLEMENTED
    reader: SourceReader | None = None
```

The declaration is data, not behaviour, because FR-028 and FR-032 both need it **enumerable and
printable** — `sources kinds` renders it, `--json` serialises it, and validation walks it. A validation
library would enforce the same constraints while making them hard to describe (see research D4).

## The reader

```python
class SourceReader(Protocol):
    def validate(self, source: ConfiguredSource) -> Sequence[Finding]:
        """Kind-specific checks beyond the declaration — a path that does not exist,
        two settings that contradict each other. Offline: MUST NOT contact anything."""

    def check_live(self, source: ConfiguredSource, credential: CredentialHandle) -> LiveCheckResult:
        """Confirm the source is reachable and the credential accepted. Read-only."""

    def read(
        self, source: ConfiguredSource, credential: CredentialHandle, since: datetime | None
    ) -> Iterator[RawRecord]:
        """Yield records at or after `since`. Read-only. Streams rather than accumulating."""
```

### There is no write operation

Not "must not write" as a rule a connector could break — **no method through which a connector could
express a write**. Principle II ("Read-Only at the Source") holds at the type level rather than by review.
`CredentialHandle` is likewise opaque: it authenticates a request and has no accessor returning the
secret, so a reader cannot log or store one even by accident (FR-022, D7).

## Registration

```python
# kinds/registry.py — an explicit mapping, populated by direct import.
_KINDS: Final[Mapping[str, SourceKind]] = {k.name: k for k in (
    fixture.KIND, git_local.KIND,
    mail.OUTLOOK, mail.GMAIL, mail.HEY,
    calendar.OUTLOOK, calendar.GOOGLE,
)}
```

FR-031 is satisfied by construction: there is no code path that scans the filesystem, reads entry points,
or dynamically imports anything, so external loading cannot be enabled by accident or by a stray file.
Relaxing it later means adding a discovery function that populates this same mapping — no change to this
contract, and no change to any user's configuration file (FR-030, FR-032).

## What a new kind must supply

1. A `SourceKind` declaration — name, summary, settings, credential requirement, access statements,
   destinations.
2. A `SourceReader`, or `reading = NOT_YET_IMPLEMENTED` and no reader.
3. An entry in `_KINDS`.
4. Its own spec and plan, per the constitution — including the exact endpoints or paths it reads, the
   credential scopes it needs, and how long it retains raw data.

Nothing else. In particular a new kind must **not** need changes to the loader, the validator, the CLI, or
any other kind — which is precisely what User Story 4 tests by registering a fixture kind and asserting
that no existing kind and no existing configuration file changed (SC-008).

## The three declared-but-unread kinds

`git.local`, `mail.*`, and `calendar.*` ship here as declarations with `reading = NOT_YET_IMPLEMENTED` and
no reader. This is FR-033: the configuration can express them today (FR-035 to FR-037), and their reading
behaviour is specified per kind in `0003`, `0004`, and `0005`.

They report readiness `NOT_READABLE` rather than `READY`, so the tool never claims a source will be read
when it will not. When `0003` lands, it adds a reader and flips one enum value — no user's configuration
file changes.
