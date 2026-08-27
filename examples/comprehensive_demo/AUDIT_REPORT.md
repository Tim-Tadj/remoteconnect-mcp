# PRJ/STU consistency audit

Audit target: `RemoteConnect_All_Objects_Demo.prj` and its paired STU.

## Passed

- Native x70 configuration export: 25 sheets
- Configuration relationship graph: clean
- Live-editor data-log identifier rules: clean
- All 14 custom `DEMO_*` objects have an exact-name, exact-DDT STU variable
- All 14 custom objects are referenced by MAST section `ObjectRegisterDemo`
- Isolated full logic rebuild: `built_ok`, zero errors and zero warnings
- Source PRJ/STU files were not modified and no UI automation was used

## Synchronization gap

The PRJ contains 64 logic-backed objects, but the STU contains matching variables for only
the 14 custom demo objects. The remaining 48 default SP575 physical-I/O objects—such as
`PIO_SP575_AI1`, `PIO_SP575_DI1`, and `PIO_SP575_CI1`—plus two logic-backed system
objects do not exist in the independently created STU.

This is a cross-project synchronization failure even though the current ST section builds.
The next remediation phase should generate or synchronize those 50 managed variables with
their exact PRJ DDTs, rebuild a copy, rerun this audit, and publish only when all 64 match.
