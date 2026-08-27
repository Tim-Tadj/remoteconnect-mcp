(* RemoteConnect comprehensive object and protocol-register demonstration. *)
DemoHeartbeat := NOT DemoHeartbeat;

(* Standard digital, DINT and REAL objects linked to Modbus scanner/register rows. *)
DEMO_MB_COIL.VALUE := DEMO_MB_DISCRETE.VALUE AND DemoHeartbeat;
DemoScaledValue := DINT_TO_REAL(DEMO_MB_INPUT_DINT.VALUE) * 0.1;
DEMO_MB_HOLD_REAL.VALUE := DemoScaledValue;

(* All five DNP3 point classes are consumed or produced by logic. *)
DEMO_DNP_DO.VALUE := DEMO_DNP_DI.VALUE;
DEMO_DNP_AO.VALUE := DINT_TO_REAL(DEMO_DNP_AI.VALUE);
DemoCounterMirror := DEMO_DNP_COUNTER.VALUE;

(* Remaining standard INT/UINT and advanced object DDT families. *)
DEMO_ANALOG_UINT.VALUE := INT_TO_UINT(DEMO_ANALOG_INT.VALUE);
DEMO_ADV_DIGITAL.VALUE := DEMO_DNP_DI.VALUE XOR DemoHeartbeat;
DEMO_ADV_ANALOG.VALUE_ENG := DemoScaledValue + UINT_TO_REAL(DEMO_ANALOG_UINT.VALUE);
DEMO_ADV_ANALOG.VALUE_RAW := REAL_TO_DINT(DEMO_ADV_ANALOG.VALUE_ENG);
DEMO_ADV_COUNTER.VALUE := DemoCounterMirror;
