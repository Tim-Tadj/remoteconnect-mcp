# Stack assessment

Reviewed on 12 October 2026 against this checkout and official documentation.
Recommendation: keep Python for the domain logic and MCP facade, and keep the
x86 .NET Framework child for the installed FDT/DTM runtime. Simplify and harden
the boundaries before considering a rewrite. The dominant uncertainty is
Schneider runtime compatibility, not the implementation language.

## What the stack actually does

| Layer | Existing choice | Assessment |
| --- | --- | --- |
| MCP transport and tools | Python, official `mcp` SDK's v1 `FastMCP`, stdio | Good local fit; no HTTP hosting/authentication burden |
| Logic editor | `pywin32`, UDE COM broker, one STA worker | Appropriate affinity model; vendor calls must remain serialised |
| x70 configuration | Privately compiled x86 .NET Framework C# child using installed FDT/DTM DLLs | Retains the vendor compatibility boundary without reusing a replaceable executable cache |
| Project inspection | XML and ZIP metadata inspection with opaque DTM data left uninterpreted | Retain a safe metadata path independent of vendor deserialisation |
| Configuration exchange | `xlrd` and `xlutils` for native BIFF `.xls` | Matches the vendor's exchange format; modern `.xlsx` libraries are not a substitute |
| Schema validation | `lxml` against installed exchange schemas | Keep; successful XML validation is weaker than a successful vendor import/build |
| Optional live values | `pymodbus`, separate online tools | Useful optional channel; keep outside the normal offline workflow |

This architecture can use 64-bit Python for its MCP/domain layer while the FDT
child stays x86. Do not require 32-bit Python merely because the DTM assemblies
are 32-bit. Conversely, moving that child to .NET 8/10 without proving vendor
assembly compatibility would remove an intentional compatibility boundary.

The C# bridge uses installed service types and reflection to reach vendor
internals. Those are version-sensitive dependencies. The source has a hardcoded
x70 DTM assembly search directory. This audit removed the shared helper cache:
each native invocation compiles into a fresh private temporary directory and
keeps its generated runtime configuration there. A tested installation matrix
and useful diagnostics remain necessary. Public Schneider descriptions of FDT/DTM configuration do not
establish a support contract for these reflected internals.

## Immediate optimisations and decisions

| Decision | Benefit | Limit or follow-up |
| --- | --- | --- |
| Keep local stdio | Small operational surface; naturally binds native software to the workstation | A stdio connection is not an OS permission boundary |
| Expose a small x70 tool profile by default | Less irrelevant catalogue data and fewer accidental generic operations | Measure schema bytes and real task calls rather than assuming a token percentage |
| Use client output budgets and focused ST/CSV reads | Reduces unnecessary source data in context | Broad result-size limits still need a server-side design that preserves full diagnostics |
| Keep reads and copy editing separate from online control | Clear review and commissioning boundary | Native vendor input must still be trusted |
| Stage, validate and publish copies atomically | Protects originals and avoids leaving apparently valid partial outputs | Audit multi-file project publication and file-alias behaviour |
| Keep expensive vendor imports/builds coarse | Reduces repeated work and write-token churn | A long tool still needs progress, cancellation and recovery design |
| Use dependency floors matching actual APIs | Prevents installs that satisfy metadata but fail at runtime | Test the declared minimum as well as the selected environment |

The implemented profiles expose 20 inspection tools or 42 default offline
tools, compared with 72 tools in the previous default. The `full` profile exposes
74 tools without online access and 87 with its 13 equipment tools enabled.
These are catalogue counts, not tokenizer measurements. The async MCP wrapper
offloads work through one AnyIO capacity limiter, preserving transport
responsiveness while serialising session operations.

Validated single files publish through sibling candidates and atomic
publication. Creating a new PRJ/STU pair now requires a **new output directory**:
both files are staged, built, saved and reopened before the directory is
published by exclusive same-filesystem rename. `overwrite=true` and an existing
pair directory are rejected. This intentionally changes the old overwrite
behaviour to preserve pair consistency.

The initial `pymodbus>=3.5,<4` requirement allowed versions that do not accept
the code's `device_id` keyword. PyModbus documents the `slave` to `device_id`
change in 3.10. The audit raises that floor; unnecessary broad compatibility
would increase maintenance cost. See
[PyModbus API changes](https://pymodbus.readthedocs.io/en/latest/source/api_changes.html).

The official Python SDK now treats v2 as stable and v1 as a maintained line.
Keep the `<2` guard while this code imports `mcp.server.fastmcp`, and choose a
tested v1 minimum that includes the APIs actually used. This audit selects
`mcp>=1.30.0,<2` and `pymodbus>=3.10,<4`. Plan a separate v2
migration rather than silently relaxing the upper bound. See the
[official v1 status](https://py.sdk.modelcontextprotocol.io/v1/) and
[v2 migration guide](https://py.sdk.modelcontextprotocol.io/migration/).

## What to improve next

1. Split tool registration by domain after the public profile contract settles:
   bundle inspection, x70 copy editing, logic reading/authoring and optional
   online control. Keep shared validation in a small policy layer. Splitting a
   file alone does not reduce tokens; registering fewer definitions does.
2. Replace loose helper stdout key/value parsing with a versioned JSON result
   envelope containing operation, status, diagnostics and output paths. Continue
   capturing vendor chatter separately so stdout cannot corrupt MCP JSON-RPC.
3. Complete cancellation/recovery design. COM waits are now bounded and an
   unknown timeout disables the session, but a timeout does not kill vendor
   work. Do not automatically retry non-idempotent operations. A child-process
   timeout does not describe every vendor process it might have started.
4. Benchmark the private helper compilation cost before optimising it. A future
   prebuilt helper or process-private cache needs verified provenance, private
   configuration and explicit compatibility checks. Do not restore the shared
   executable cache merely to improve start-up time.
5. Keep the added `uv.lock` and frozen installation checks current. Extend
   Windows CI with protocol discovery, profiles and path policy. Keep native
   vendor import/build tests as an explicit licensed workstation suite. A mock
   test cannot certify a Schneider runtime version.
6. Evaluate optional dependency groups only when they produce a concrete smaller
   installation. `pymodbus` can be optional for offline deployments. The `.xls`
   reader/writer stack is necessary for x70 configuration exchange. Avoid adding
   pandas, an ORM or a web framework to handle operations already covered here.

Native configuration round trips intentionally cost more than XML edits. That
cost buys vendor format interpretation and post-import verification. Reusing a
persistent FDT host could reduce repeated start-up time, but introduces state,
write-token and crash-recovery complexity. Benchmark on disposable projects
before adopting it. Retain full builds for final publication; introduce an
incremental build cache only with a reliable project/version fingerprint.

## Rewrite alternatives

| Alternative | Potential gain | Why it is not the first move |
| --- | --- | --- |
| All C# MCP service | One main language, direct .NET access, stronger native DTOs | Still needs x86/vendor runtime handling and COM affinity; rewrites substantial tested parsing/copy logic |
| TypeScript / Node MCP | Convenient MCP distribution and Claude Desktop's bundled Node runtime | Still needs a Windows native helper for COM/FDT; adds a third boundary or requires the same rewrite |
| Python with `pythonnet` in-process | Removes one child process | Couples Python bitness/runtime to vendor .NET, weakens crash isolation and changes deployment substantially |
| Cloud HTTP service | Shared remote clients | Cannot run the workstation's vendor broker without a Windows host; adds authentication, concurrency and process isolation |
| UI automation | Covers features absent from APIs | Fragile window/state dependency and poorer deterministic validation; reserve for a specifically unsupported action |

An all-C# prototype becomes reasonable if measurements show Python/native
marshalling or the dual runtime dominates cost, or if the team can maintain C#
more effectively. A TypeScript rewrite is justified by team/deployment needs,
not a presumed token advantage. Tool schemas, catalogue size, result size and
workflow shape affect model context regardless of the implementation language.

## Schneider scope and evidence limits

RemoteConnect's x70 DeviceDTM configuration path differs from generic Control
Expert M580 CPU/slave DTM tooling. Schneider's own configuration instructions
identify `SCADAPack x70 Controller Settings - DeviceDTM` and its project settings.
That supports the product distinction, not the repository's internal APIs. See
[Schneider project settings](https://www.se.com/us/en/faqs/FA377985/).

Schneider lists the PC CommDTM's supported connections and states that the logic
editor requires TCP/IP, so serial communication does not provide logic-editor
access. Its FAQ also excludes Modbus RTU encapsulated in TCP/UDP in that context.
Do not transfer M580 DTM scanner assumptions or simulator behaviour to x70
without a native x70 test. See [Schneider CommDTM limitations](https://www.se.com/us/en/faqs/FAQ000260855/).

The [current audit report](AUDIT_REPORT.md) records a successful native ST
comment-only edit through the installed UDE broker: source read, clean full
build, save, source-equal reopen and clean rebuild. Original files remained
hash-identical; the accompanying PRJ/RCZ/parameter CSVs were copied byte-for-byte.
This supports the logic-only milestone, not a configuration import, complete
SCADAPack download or hardware claim. Native FDT compatibility and Cowork
hosting require separate evidence on the intended installation.
