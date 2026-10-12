# Fork audit and offline integration

Audit date: 12 October 2026. Scope: local project inspection, source reading,
copy editing, validation and MCP installation. No controller connection,
transfer, start/stop or live-value operation was performed.

## Outcome and evidence

The Parameters comment-only logic milestone passed through the installed
UnitySoControl/UDE COM interface. The test used disposable copies and obtained
proper native Structured Text, rather than recovered STU database text.

| Check | Result |
| --- | --- |
| Native Parameters source | Read successfully; 10,493 characters before editing |
| Change | One added comment: `(* Offline MCP audit: comment-only review copy. *)` |
| Full build before saving | `built_ok`, 0 errors, 0 warnings |
| Save and native logic reopen | Passed; reopened ST source matches the requested text |
| Full rebuild after reopening | `built_ok`, 0 errors, 0 warnings |
| Original project directory | All recorded original file SHA-256 hashes unchanged |
| Reviewed PRJ and parameter CSVs; reference RCZ | Byte-identical to their corresponding inputs |
| Native configuration export/reopen | Passed before and after: 25 sheets, two DTMs, no cancellation, exit code 0 |
| Native before/after configuration | Equal under full bidirectional canonical comparison |
| Real MCP source call | Passed over stdio; all 10,544 edited source characters match the expected source |
| Manual RemoteConnect GUI reopen | Not verified |
| Configuration/logic bindings | Subsequent native audit passes: 939/939 typed bindings; no errors, warnings or unverified paths |
| Physical equipment | No operations performed |

Local evidence and review files are intentionally ignored by Git:

- [Integration report](../.tools/integration/comment-only-01/report.json).
- [Parameters source diff](../.tools/integration/comment-only-01/Parameters.diff).
- [Native configuration evidence](../.tools/integration/comment-only-01/native-export-report.json).
- [Real MCP source-call evidence](../.tools/integration/comment-only-01/mcp-source-report.json).
- [Native consistency audit](../.tools/integration/comment-only-01/consistency-report.json).
- [Reviewed project directory](../.tools/integration/comment-only-01/reviewed/).
- [Repeatable offline test](../tools/offline_smoke.py).

Open the reviewed PRJ when reviewing the change. The original RCZ is kept under
`reference-archives`, because it embeds the original STA/APX and has not been
rebuilt to contain the edited logic. It must not be treated as an updated
download/archive bundle.

The original PRJ was initially locked by another process. The test proceeded
after the user saved and closed it. A clean snapshot was hashed before copying;
the test neither opened that original in COM nor saved it.

The workstation reports Control Expert 16.2.05275 and RemoteConnect 4.6.17290.
Python is 64-bit CPython 3.12.14. The native configuration child targets x86
.NET Framework. RemoteConnect is installed under `D:\Program Files\RemoteConnect`,
which differs from the repository's former default path.

The first configuration attempt failed because the default install directory
was absent. Registry-based installation discovery and `REMOTECONNECT_HOME`
now support non-default paths. During hardening, an absolute private config
argument exposed a vendor string-concatenation requirement. Inspection of the
installed framework identified it, and the helper now passes a relative filename
while keeping the file in its private directory. The subsequent two native
exports and reopens passed. This is verified compatibility on this installation,
not an official support guarantee for the reflected interfaces.

## Confirmed findings and fixes

Severity describes the pre-fix implementation, supported by source inspection
and focused regression tests. A test of a mocked vendor interface is not a
claim that every Schneider software release has been validated.

| Severity | Finding | Implemented correction |
| --- | --- | --- |
| High | Opening or creating another application silently closed the current session without saving | Active sessions require an explicit close; copy/create workflows use isolated bridges |
| High | Close failures were suppressed and the application binding was forgotten | Failed close retains application and project state and reports failure |
| High | Simulator start/stop bypassed the online gate; start could weaken a registry security setting | Both require the full profile and online opt-in; security is preserved by default and registry changes need a separate explicit argument |
| High | Native stdout parsing ignored cancellation fields later on a tab-separated line | Parse every field, reject cancellation/non-zero exit, and do not save rejected imports |
| High | Failed or partial configuration imports could be published through `require_clean=False`; comparison missed ordinary field changes/removals | Failure always withholds publication; canonical comparison covers table fields and requested replace-all removals |
| Medium | XML restrictions relied on dependency defaults and schema includes were not confined | Bounded XML parsing rejects DTDs/entities, disables networking and restricts XSD includes to the local schema directory; local-file disclosure was not reproduced on current lxml |
| High | Direct output writes could damage an existing destination or leave a mismatched PRJ/STU pair | Validated sibling-file publication; reject source aliases; new pairs publish by exclusive same-filesystem directory rename |
| High | Edited archive materialisations could be deleted or reused as if pristine | Separate pristine cache from unique session working files; preserve edited materialisations |
| Medium | Shared thread names were used as proof of COM apartment ownership, and waits were unbounded | Per-instance worker identity, balanced apartment lifetime, bounded waits and disabled sessions after unknown timeout outcomes |
| Medium | Failed ZEF restoration could still be described as restored | Report rollback failure and retain recovery exports |
| Medium | Reusable generated helper executables and runtime settings were shared across calls | Compile in a fresh private temporary directory and keep generated configuration there |
| Medium | Long synchronous tools blocked the MCP event loop | Offload tools to a worker with one capacity limiter; protocol pings remain responsive and session operations do not interleave |
| Medium | The consistency audit treated array elements as absent top-level variables | Resolve native arrays and member paths, validate bounds/casing/terminal type, distinguish unknown definitions and literal versus base-only references |
| Medium | Tool path parameters had no configured workspace boundaries | Read/write root allowlists, resolved-path checks, bundle-member checks, network/alternate-stream rejection and save-in-place checks |
| Medium | Installation examples named the wrong module; declared dependency versions permitted incompatible APIs | Correct `remoteconnect_mcp`/`remoteconnect-mcp` examples, tested SDK floor, PyModbus API floor and a frozen `uv.lock` |

Review also found and fixed quoted-description corruption in the newly added CSV
copy writer. Expected old values are mandatory, unsupported new quoting is
rejected, and comments, existing quoted identifiers/descriptions, encoding and
line endings are preserved.

## Client integration and stack

[Client guidance](MCP_CLIENTS.md) and checked configuration samples cover Codex,
native Claude Code, Claude Desktop and the conditional Cowork local-plugin
route. The plugin manifest passed the installed Claude CLI's strict validator.
Configuration samples remain reviewable templates; global client settings were
not changed.

The server now provides 20 inspection tools or 42 default offline tools. The
previous default exposed 72 definitions. This is a 41.7% reduction in tool
count, not a measured 41.7% reduction in model tokens. Source paging, filters,
concise server instructions and client output budgets reduce unnecessary context.
Tool annotations distinguish reads from actions, while server-side gates remain
the enforcement mechanism.

The [stack assessment](STACK_ASSESSMENT.md) recommends retaining Python, the
official MCP SDK, pywin32 and the separate x86 vendor child. A language rewrite
would not resolve the version-sensitive Schneider framework dependencies.
The frozen installation was successfully rebuilt from the local dependency
cache and dependency compatibility checks passed. Selected versions include
MCP 1.30.0, pywin32 312, lxml 6.1.3 and PyModbus 3.16.1.
The [compatibility review](COMPATIBILITY.md) documents Schneider's x70 FDT
framework limits and the distinction between `/user` file search and relative
file opening.

## Validation

The final regression run passed 123 tests, with one further test skipped
because this Windows account cannot create a symlink. The hard-link alias test
passed outside the filesystem sandbox. Tests cover COM ownership/timeouts and
close failures using fakes, archive limits, atomic publication, cancellation,
partial imports, all-field configuration comparison, path policy, CSV preservation,
native array/member resolution, concurrent source changes and release payload
confinement/client configuration.

Five protocol tests use actual stdio JSON-RPC and the package entry point. Their
bootstrap blocks vendor/equipment activation. They check all profile/opt-in
combinations, tool annotations, path rejection, simulator registry arguments,
responsive pings and serial tool execution. A separate read-only integration
opened the reviewed copy through the real MCP process, read Parameters and
closed without saving. Source equality passed.

Python compile checks, whitespace checks, JSON/TOML sample parsing, strict Claude
plugin validation and the frozen dependency installation also passed. Native
configuration import/write scenarios remain mocked. The minimum supported Python
and dependency versions were not separately exercised; this workstation used
the selected versions above.

## Git destination protection

This checkout now uses the Tim-Tadj fork as the default and branch push remote.
`upstream` remains available for fetching and its push URL is `DISABLED`.
The local `core.hooksPath` points to the tracked `.githooks` directory. Its
pre-push hook allows only the Tim-Tadj fork, including when an explicit remote
URL is supplied. Direct hook checks accepted the fork and rejected upstream.
GitHub CLI's resolved base points to the fork.

These are safeguards against accidental pushes. A user can deliberately bypass
a local hook or change Git configuration. The safeguards are active in this
checkout; another clone must set its local Git configuration and hook path.
Publication targets the fork. No upstream pull request was created.

## Limits and failure recovery

- A COM timeout does not cancel vendor work. Its outcome is unknown, and the
  bridge refuses further operations until restarted. Inspect/recover the
  disposable project before retrying. Do not assume process exit preserves an
  unsaved session; save or explicitly close it first.
- Read/write root checks are application controls, not an OS sandbox for
  installed vendor assemblies. Native deserialisation must receive trusted
  engineering files. The read-only metadata inspector leaves opaque DTM payloads
  uninterpreted.
- No outbound HTTP service, telemetry or project upload was found in repository
  implementation code. Optional Modbus tools deliberately access configured
  endpoints. AI clients may transmit returned source to their model provider;
  that is outside this server's network implementation.
- This run proves the stated ST comment edit, save and native logic reopen.
  It does not establish LD/FBD/SFC editing, archive materialisation on this
  workstation, configuration imports, firmware compatibility or a complete
  SCADAPack configuration-plus-logic download.
- The subsequent consistency audit read 966 variables, 27 sections and 30 native
  type definitions. All 939 logic-backed configuration bindings match. Reference
  occurrences remain lexical evidence; dynamic array use does not establish
  which elements execute at runtime. Automatic variable generation refuses
  composite object names rather than inventing array bounds or member types.
- Parameter CSV filename derivation and reload/status logic were read from
  proper Parameters source. Relative file-open directory behaviour and runtime
  reads were not tested on equipment. CSV copies are text-validated, not
  controller-validated.
- Customer integration artefacts remain in ignored `.tools/`; native helper
  code and public regression fixtures contain no copied customer source.
