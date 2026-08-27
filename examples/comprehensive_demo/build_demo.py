"""Rebuild the comprehensive RemoteConnect demo without UI automation."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from remoteconnect_mcp.bulk_edit import create_objects_copy, create_parent_entities_copy
from remoteconnect_mcp.native_bridge import create_configuration_project, export_configuration


HERE = Path(__file__).resolve().parent
PROJECT = HERE / "RemoteConnect_All_Objects_Demo.prj"
XPDF = Path(
    r"C:\ProgramData\Schneider Electric\CommonControlExpert\16.2"
    r"\Xpdf\SCBForSCADAPack.xpdf"
)


def relationships(*extra: dict) -> list[dict]:
    return [
        {"kind": "browser", "list_name": "MCP Demo Objects"},
        {"kind": "data_log", "log_name": "MCP_Demo_Log"},
        *extra,
    ]


def object_specs() -> list[dict]:
    specs = [
        ("DEMO_MB_COIL", "PIO_SP575_DI1", {"Comment": "Modbus coil 00001", "ModbusRegister": 1},
         {"kind": "modbus_scanner_point", "scanner_sequence_id": 1, "register_address": 1}),
        ("DEMO_MB_DISCRETE", "PIO_SP575_DI1", {"Comment": "Modbus discrete input 10001", "ModbusRegister": 10001},
         {"kind": "modbus_scanner_point", "scanner_sequence_id": 2, "register_address": 10001}),
        ("DEMO_MB_INPUT_DINT", "PIO_SP575_AI1", {"Comment": "Modbus input register 30001 DINT", "ModbusRegister": 30001},
         {"kind": "modbus_scanner_point", "scanner_sequence_id": 3, "register_address": 30001}),
        ("DEMO_MB_HOLD_REAL", "PIO_SP575_Cin1_Freq", {"Comment": "Modbus holding registers 40001-40002 REAL", "ModbusRegister": 40001},
         {"kind": "modbus_scanner_point", "scanner_sequence_id": 4, "register_address": 40001}),
        ("DEMO_DNP_DI", "PIO_SP575_DI1", {"Comment": "DNP3 binary input point 1"},
         {"kind": "dnp_point", "point_sequence_id": 1}),
        ("DEMO_DNP_DO", "PIO_SP575_DI1", {"Comment": "DNP3 binary output point 2"},
         {"kind": "dnp_point", "point_sequence_id": 2}),
        ("DEMO_DNP_AI", "PIO_SP575_AI1", {"Comment": "DNP3 analog input point 3"},
         {"kind": "dnp_point", "point_sequence_id": 3}),
        ("DEMO_DNP_AO", "PIO_SP575_Cin1_Freq", {"Comment": "DNP3 analog output point 4"},
         {"kind": "dnp_point", "point_sequence_id": 4}),
        ("DEMO_DNP_COUNTER", "PIO_SP575_CI1", {"Comment": "DNP3 counter input point 5"},
         {"kind": "dnp_point", "point_sequence_id": 5}),
    ]
    result = [
        {"name": name, "prototype": prototype, "values": values,
         "relationships": relationships(link)}
        for name, prototype, values, link in specs
    ]
    for name, prototype, values in [
        ("DEMO_ANALOG_INT", "PIO_SP575_AI1", {"Comment": "INT object at input register 30010", "LogicVariableType": "T_SPx70_INT <2>", "ModbusRegister": 30010}),
        ("DEMO_ANALOG_UINT", "PIO_SP575_AI1", {"Comment": "UINT object at holding register 40010", "LogicVariableType": "T_SPx70_UINT <3>", "ModbusRegister": 40010}),
        ("DEMO_ADV_ANALOG", "PIO_SP575_AI1", {"Comment": "Advanced analog object", "LogicVariableType": "T_SPx70_ADV_ANALOG <7>"}),
        ("DEMO_ADV_DIGITAL", "PIO_SP575_DI1", {"Comment": "Advanced digital object", "LogicVariableType": "T_SPx70_ADV_DIGITAL <8>"}),
        ("DEMO_ADV_COUNTER", "PIO_SP575_CI1", {"Comment": "Advanced counter object", "LogicVariableType": "T_SPx70_ADV_COUNTER <9>"}),
    ]:
        result.append({"name": name, "prototype": prototype, "values": values,
                       "relationships": relationships()})
    return result


def logic_variables() -> list[dict]:
    types = {
        "DEMO_MB_COIL": "T_SPx70_BOOL", "DEMO_MB_DISCRETE": "T_SPx70_BOOL",
        "DEMO_MB_INPUT_DINT": "T_SPx70_DINT", "DEMO_MB_HOLD_REAL": "T_SPx70_REAL",
        "DEMO_DNP_DI": "T_SPx70_BOOL", "DEMO_DNP_DO": "T_SPx70_BOOL",
        "DEMO_DNP_AI": "T_SPx70_DINT", "DEMO_DNP_AO": "T_SPx70_REAL",
        "DEMO_DNP_COUNTER": "T_SPx70_UDINT", "DEMO_ANALOG_INT": "T_SPx70_INT",
        "DEMO_ANALOG_UINT": "T_SPx70_UINT", "DEMO_ADV_ANALOG": "T_SPx70_ADV_ANALOG",
        "DEMO_ADV_DIGITAL": "T_SPx70_ADV_DIGITAL", "DEMO_ADV_COUNTER": "T_SPx70_ADV_COUNTER",
    }
    result = [{"name": name, "type": type_name, "comment": "RemoteConnect demo object"}
              for name, type_name in types.items()]
    result.extend([
        {"name": "DemoHeartbeat", "type": "BOOL", "comment": "Demo logic heartbeat"},
        {"name": "DemoScaledValue", "type": "REAL", "comment": "Scaled Modbus value"},
        {"name": "DemoCounterMirror", "type": "UDINT", "comment": "Counter mirror"},
    ])
    return result


def build(overwrite: bool) -> dict:
    if not os.environ.get("CE_MCP_XPDF_CONTEXT"):
        os.environ["CE_MCP_XPDF_CONTEXT"] = str(XPDF)
    # Import only after setting the OEM context; bridge constants are read at import time.
    from remoteconnect_mcp.server import create_remoteconnect_project

    with tempfile.TemporaryDirectory(prefix="remoteconnect-demo-") as directory:
        stage = Path(directory)
        seed_prj = stage / "seed.prj"
        seed_xls = stage / "seed.xls"
        parents_xls = stage / "parents.xls"
        objects_xls = stage / "objects.xls"
        create_configuration_project(str(seed_prj))
        export_configuration(str(seed_prj), str(seed_xls))
        create_parent_entities_copy(
            str(seed_xls), str(parents_xls),
            browser_lists=[{"name": "MCP Demo Objects"}],
            data_logs=[{"name": "MCP_Demo_Log"}],
            modbus_devices=[{"name": "Demo_Modbus_PLC", "values": {"IpAddress": "192.168.10.50"}}],
            modbus_scanners=[
                {"device_name": "Demo_Modbus_PLC", "register_start": 1, "register_quantity": 8, "values": {"ModbusDataType": "Discrete <1>", "ObjectType": "Digital <1>"}},
                {"device_name": "Demo_Modbus_PLC", "register_start": 10001, "register_quantity": 8, "values": {"ModbusDataType": "Discrete <1>", "ObjectType": "Digital <1>"}},
                {"device_name": "Demo_Modbus_PLC", "register_start": 30001, "register_quantity": 8, "values": {"ModbusDataType": "DINT <4>", "ObjectType": "Analog <0>"}},
                {"device_name": "Demo_Modbus_PLC", "register_start": 40001, "register_quantity": 8, "values": {"ModbusDataType": "REAL (Floating Point) <6>", "ObjectType": "Analog <0>"}},
            ],
            dnp_devices=[{"name": "Demo_DNP3_Outstation", "values": {"DeviceAddress": 10}}],
            dnp_points=[
                {"device_name": "Demo_DNP3_Outstation", "remote_point_number": 1, "point_type": "digital_input"},
                {"device_name": "Demo_DNP3_Outstation", "remote_point_number": 2, "point_type": "digital_output"},
                {"device_name": "Demo_DNP3_Outstation", "remote_point_number": 3, "point_type": "analog_input"},
                {"device_name": "Demo_DNP3_Outstation", "remote_point_number": 4, "point_type": "analog_output"},
                {"device_name": "Demo_DNP3_Outstation", "remote_point_number": 5, "point_type": "counter_input"},
            ],
        )
        create_objects_copy(str(parents_xls), str(objects_xls), object_specs())
        result = create_remoteconnect_project(
            str(PROJECT), "SCADAPack57x", task="MAST", section="ObjectRegisterDemo",
            st_source=(HERE / "ObjectRegisterDemo.st").read_text(encoding="utf-8"),
            variables=logic_variables(), configuration_workbook=str(objects_xls),
            overwrite=overwrite,
        )
        if result.get("ok"):
            export_configuration(str(PROJECT), str(PROJECT.with_suffix(".xls")), overwrite=True)
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    outcome = build(args.overwrite)
    print({"ok": outcome.get("ok"), "published": outcome.get("published"),
           "configuration": outcome.get("configuration_path"), "logic": outcome.get("logic_path")})
