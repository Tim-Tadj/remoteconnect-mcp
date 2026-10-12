# Schneider compatibility and parameter CSV evidence

Reviewed on 12 October 2026. Product documentation, repository behaviour and
workstation tests are separate forms of evidence. A successful local test does
not establish Schneider support for a reflected internal API.

## RemoteConnect's x70 framework boundary

Schneider's *SCADAPack x70 Configuration*, version 3.9.1, explains that its x70
DeviceDTM needs additional RemoteConnect framework services and is not designed
for external third-party FDT 2.1 frames. This is an explicit product limitation,
despite FDT standards compliance. See the section on external FDT frames,
printed page 23, in the [Schneider-authored configuration manual](https://d2uars7xkdmztq.cloudfront.net/app_resources/58663/documentation/281078_en-US.pdf#page=23).

The repository's C# helper uses installed RemoteConnect service assemblies and
the vendor catalogue, then reflects non-public x70 workbook APIs. It does not
implement an independent, complete FDT frame. **Inference:** reusing those
services may satisfy more dependencies than hosting the DTM in an arbitrary
frame, but the manual does not endorse this helper, its reflection calls or its
headless environment. Treat this route as version-sensitive integration.

The helper uses an x86 .NET Framework process independently of Python's
bitness. An installed catalogue, compatible framework/DTM assemblies and their
configuration files remain necessary. `REMOTECONNECT_HOME` selects the intended
installation explicitly. Without it, the package checks exact `RemoteConnect`
uninstall registrations with an existing `RuntimeFrame.dll`, then the standard
installation directory. Ambiguous installations require an explicit selection.

Generated helper binaries, runtime settings and runtime temporary files are
placed in a fresh helper directory. Reflection-only inspection of the installed
service DLL confirmed that its config loader concatenates the entry-assembly
directory with a relative config name. An absolute constructor argument fails;
an adjacent private config with a relative name preserves that contract.

Native calls can still use installed catalogues, licensing services and vendor
user settings. Server path restrictions control explicit tool paths. They do
not sandbox vendor DLLs or turn their proprietary deserialisation into a safe
untrusted-file reader. Use trusted project files and a disposable workspace.

## Configuration, logic and device transfer

The same manual distinguishes offline configuration from changes applied to
equipment, and lists full configuration/logic transfer as online functionality.
It also documents XLS object exchange and the RemoteConnect import route for
logic projects. See [offline and online functionality, printed pages 24-29](https://d2uars7xkdmztq.cloudfront.net/app_resources/58663/documentation/281078_en-US.pdf#page=24).

The local implementation therefore verifies configuration imports through
feedback, save/reopen and native re-export of requested changes. A logic build
checks the logic application. Both checks are needed when objects and logic
variables change together. Neither check proves live controller behaviour or
constitutes a complete SCADAPack download implementation.

Generic Control Expert transfer, M580 DTM or simulator tools must not be treated
as x70 commissioning workflows. Schneider also documents PC CommDTM connection
limits and the logic editor's TCP/IP requirement in its [CommDTM FAQ](https://www.se.com/us/en/faqs/FAQ000260855/).

## Parameter CSV file selection

Schneider's *SCADAPack Function Blocks Technical Reference*, document 250530,
version 3.9.1, specifies `/user` for `F_FindFile` when its `DIR` input is omitted.
Its `F_ROPEN` documentation says a bare filename is resolved using the current
working directory. These are distinct rules. See the [Schneider-authored
function-block manual, printed pages 90 and 96](https://d2uars7xkdmztq.cloudfront.net/app_resources/58663/documentation/343025_1641414807332_en-US.pdf#page=90).

The proper `Parameters` source exported from a disposable copy during this
audit calls an `F_FindFile` instance without `DIR`. It copies the configured
DNP3 slave address to the numeric address used for filename construction,
and resets the reload request after handling it.
The site's CSV is runtime data, separate from the vendor XLS import workbook.
For address zero, the expected filename is `0.csv`.

The native variable export confirms the block's `F_FindFile` type.
The documented omitted-`DIR` search rule therefore applies to
that call, subject to the manual-version qualification below.

**Unverified:** the CSV reader's underlying `fopen` implementation and the
controller's working directory when
that call executes. No retrieved x70 documentation explicitly established this
custom reader's `fopen` behaviour. The documented `F_ROPEN` rule cannot be
substituted for that evidence. Finding a file through a default `/user` search
does not prove that a separate relative open resolves to the same location.

Before commissioning a path change, inspect the complete CSV reader and any
`F_CD`/`F_PWD` calls. Review an explicit `/user/0.csv` path or a deliberately
managed working directory in a project copy. Do not change either path solely
from the search block's default. The reported site success indicators are a
zero read status, a false initialisation-error flag and an updated successful-read
timestamp; their device behaviour was not tested here. Project-specific tag
names remain in the ignored local evidence.

## Source and test limits

The linked PDFs are original Schneider-authored manuals hosted on a public
documentation mirror. The mirror is not an official Schneider distribution
endpoint. Direct Schneider download records for documents 250523 and 250530
were inaccessible during this research. The available manual revisions do not
prove identical behaviour in every installed release. Check the exact version
of installed RemoteConnect help and record the installed DTM/framework versions
when accepting a native round trip.

Mock tests exercise cancellation, failed imports, XML entity rejection, schema
boundaries and atomic publication. Repository XLS fixtures exercise field and
relationship comparison. Workstation integration results need to be read
alongside those tests, with GUI reopening and controller testing recorded
separately. Opaque `.STU` database text recovery remains an inspection fallback;
it is not a source-editing or validation method.
