# Comprehensive RemoteConnect demo

This folder contains a headlessly generated, template-free SCADAPack 57x demo:

- `RemoteConnect_All_Objects_Demo.prj` — RemoteConnect configuration project
- `RemoteConnect_All_Objects_Demo.stu` — paired UnitySoControl logic project
- `RemoteConnect_All_Objects_Demo.xls` — native 25-sheet configuration export
- `ObjectRegisterDemo.st` — readable source of the built MAST section
- `build_demo.py` — reproducible programmatic generator
- `AUDIT_REPORT.md` — PRJ/STU consistency findings from the v0.17 audit

No UI automation is used. The PRJ was created from the installed CommDTM/x70 catalog,
and the STU was created from the installed SCADAPack57x logic catalog.

## Coverage

The configuration contains 14 demo objects covering every SCADAPack object DDT shipped
in the installed library:

- `T_SPx70_BOOL`, `T_SPx70_INT`, `T_SPx70_UINT`, `T_SPx70_DINT`
- `T_SPx70_UDINT`, `T_SPx70_REAL`
- `T_SPx70_ADV_ANALOG`, `T_SPx70_ADV_DIGITAL`, `T_SPx70_ADV_COUNTER`

Protocol and configuration coverage:

- Modbus/TCP device `Demo_Modbus_PLC` at `192.168.10.50`
- Coil `00001`, discrete input `10001`, input register `30001`, and holding
  register `40001` scanner ranges with linked objects
- Additional INT input register `30010` and UINT holding register `40010`
- DNP3 device address `10` with digital input, digital output, analog input,
  analog output, and counter input points
- Browser List `MCP Demo Objects`
- Data log `MCP_Demo_Log`, with project logging enabled and all 14 objects linked

The paired logic declares the same object names and DDTs. MAST section
`ObjectRegisterDemo` reads and writes their structure members (`VALUE`, `VALUE_ENG`,
and `VALUE_RAW`) so the configuration-to-logic link is explicit and build-checked.

## Validation performed

- Native x70 XLS import report: zero errors
- Native post-import re-export: no missing requested entities or relationships
- Final configuration export: 25 sheets, 14 demo objects, four Modbus scanner links,
  five DNP3 point links, and 14 data-log links
- Independent STU reopen and full build: `built_ok`, zero errors, zero warnings

## Regenerate

From the repository root in PowerShell:

```powershell
$env:CE_MCP_XPDF_CONTEXT = "C:\ProgramData\Schneider Electric\CommonControlExpert\16.2\Xpdf\SCBForSCADAPack.xpdf"
python examples\comprehensive_demo\build_demo.py --overwrite
```

The configured IP address and DNP3 address are demonstration values. Change them before
connecting the project to a real controller or field device.
