# PRJ/STU consistency audit

Audit target: `RemoteConnect_All_Objects_Demo.prj` and its paired STU.

## Passed

- Native x70 configuration export: 25 sheets
- Configuration relationship graph: clean
- Live-editor data-log identifier rules: clean
- All 14 custom `DEMO_*` objects have exact-name, exact-DDT STU variables
- All 14 custom objects are referenced by MAST section `ObjectRegisterDemo`
- All 48 default SP575 physical-I/O objects and both logic-backed system objects have
  exact-name, exact-DDT STU variables
- Synchronization result: 64 expected, 64 matched, zero missing, zero mismatched
- Isolated full logic rebuild: `built_ok`, zero errors and zero warnings
- Source PRJ/STU files were not modified and no UI automation was used

## Coverage warnings

The audit reports 50 non-critical coverage warnings because the 48 default SP575 physical-I/O
variables and two system variables are declared but not referenced by `ObjectRegisterDemo`.
This is intentional: the demonstration logic exercises the 14 custom protocol/object examples
without writing to every physical channel.

Overall audit status is `ok=true` with zero critical errors. Native relationships, editor rules,
PRJ/STU synchronization, and the full logic build all pass.
