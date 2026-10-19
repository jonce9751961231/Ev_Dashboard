"""
===============================================================================
Project: EV Dashboard & Motor Predictive Thermal Management System
File: c2000_interface.py
Description: TI C2000 SCI / UART Serial Interface and HIL Virtual Driver.
             Unpacks binary telemetry frames and streams them to the dashboard.
===============================================================================
"""

import struct
import time
import math
from typing import Optional, Dict, Any
from .motor_physics_model import PMSMMotorThermalPlant, MotorPhysicalSpecs
from .future_temp_predictor import MotorFutureTemperaturePredictor


class C2000PacketParser:
    """
    Parses and verifies binary packets received from TI C2000 SCI/UART.
    Matches struct C2000_Serial_Telemetry_Packet_t defined in c2000_telemetry.h.
    """

    # Format:
    # 2 bytes Sync (0xAA, 0x55)
    # 1 byte Version
    # 1 byte Type
    # 1 uint32 Timestamp_ms
    # 10 floats (Raw Telemetry: Phase U, V, W, Id, Iq, RPM, Torque, Vdc, I_dc, StatorT, FrameT, CoolantInT, AmbT, IGBT_T, FlowRate)
    # 9 floats + 2 uint8 (Thermal Estimate: RotorT, CoreT, Pcu, Pfe, Pmech, Ptot, Pred1m, Pred5m, PredRotor5m, MaxTorque, Flags, PumpPWM)
    # 1 uint16 Checksum CRC16
    HEADER_FORMAT = "<BBBB I"
    RAW_SENSORS_FORMAT = "11f"      # 11 floats
    THERMAL_EST_FORMAT = "9f B B"   # 9 floats, 2 uint8
    CRC_FORMAT = "H"

    FULL_PACKET_FORMAT = f"{HEADER_FORMAT} {RAW_SENSORS_FORMAT} {THERMAL_EST_FORMAT} {CRC_FORMAT}"
    PACKET_SIZE = struct.calcsize(FULL_PACKET_FORMAT)

    @staticmethod
    def calculate_crc16(data: bytes) -> int:
        """Calculates CRC-16-CCITT matching C2000 on-chip routine."""
        crc = 0xFFFF
        for byte in data:
            crc ^= (byte << 8)
            for _ in range(8):
                if crc & 0x8000:
                    crc = ((crc << 1) ^ 0x1021) & 0xFFFF
                else:
                    crc = (crc << 1) & 0xFFFF
        return crc

    @classmethod
    def unpack(cls, buffer: bytes) -> Optional[Dict[str, Any]]:
        """Unpacks and validates a binary telemetry packet."""
        if len(buffer) < cls.PACKET_SIZE:
            return None

        unpacked = struct.unpack(cls.FULL_PACKET_FORMAT, buffer[:cls.PACKET_SIZE])
        sync1, sync2, ver, p_type, timestamp_ms = unpacked[0:5]

        if sync1 != 0xAA or sync2 != 0x55:
            return None

        # Verify CRC
        payload = buffer[:cls.PACKET_SIZE - 2]
        expected_crc = unpacked[-1]
        calc_crc = cls.calculate_crc16(payload)

        if expected_crc != calc_crc:
            # Checksum mismatch
            return None

        # Extract values
        return {
            "timestamp_ms": timestamp_ms,
            "version": ver,
            "packet_type": p_type,
            "phase_u_current": unpacked[5],
            "phase_v_current": unpacked[6],
            "phase_w_current": unpacked[7],
            "i_d_current": unpacked[8],
            "i_q_current": unpacked[9],
            "motor_speed_rpm": unpacked[10],
            "motor_torque_nm": unpacked[11],
            "dc_bus_voltage_V": unpacked[12],
            "stator_temp_measured_C": unpacked[13],
            "casing_temp_measured_C": unpacked[14],
            "coolant_temp_C": unpacked[15],
            "rotor_temp_est_C": unpacked[16],
            "stator_core_est_C": unpacked[17],
            "p_copper_W": unpacked[18],
            "p_iron_W": unpacked[19],
            "p_mech_W": unpacked[20],
            "total_loss_W": unpacked[21],
            "pred_stator_1m_C": unpacked[22],
            "pred_stator_5m_C": unpacked[23],
            "pred_rotor_5m_C": unpacked[24],
            "max_allowable_torque_nm": unpacked[25],
            "thermal_warning_flags": unpacked[26],
            "pump_pwm_pct": unpacked[27]
        }


class C2000VirtualHILSimulator:
    """
    High-Fidelity Virtual Hardware-in-the-Loop (HIL) Simulator for TI C2000.
    Simulates motor drives across varied road topographies and user throttle inputs.
    """

    DRIVE_SCENARIOS = {
        "ECO_CITY": {"avg_speed": 45.0, "rpm_base": 2200, "torque_base": 90, "load_mult": 0.45, "name": "Urban City Eco Driving"},
        "HIGHWAY_CRUISE": {"avg_speed": 110.0, "rpm_base": 5600, "torque_base": 140, "load_mult": 0.70, "name": "110 km/h Highway Cruise"},
        "AGGRESSIVE_TRACK": {"avg_speed": 140.0, "rpm_base": 8200, "torque_base": 290, "load_mult": 1.25, "name": "Aggressive Sport / Track Launch"},
        "MOUNTAIN_CLIMB": {"avg_speed": 65.0, "rpm_base": 3800, "torque_base": 310, "load_mult": 1.40, "name": "12% Mountain Grade Hill Climb"},
        "COOLING_DEGRADED": {"avg_speed": 90.0, "rpm_base": 4800, "torque_base": 180, "load_mult": 0.90, "coolant_flow": 1.5, "name": "Cooling Pump Impairment (High Thermal Stress)"}
    }

    def __init__(self, ambient_temp_C: float = 30.0):
        self.plant = PMSMMotorThermalPlant(ambient_temp_C=ambient_temp_C)
        self.predictor = MotorFutureTemperaturePredictor()
        self.current_scenario = "MOUNTAIN_CLIMB"
        self.tick = 0
        self.coolant_flow_lpm = 6.0
        self.coolant_inlet_temp_C = 35.0

    def set_scenario(self, scenario_key: str):
        if scenario_key in self.DRIVE_SCENARIOS:
            self.current_scenario = scenario_key
            scen = self.DRIVE_SCENARIOS[scenario_key]
            if "coolant_flow" in scen:
                self.coolant_flow_lpm = scen["coolant_flow"]
            else:
                self.coolant_flow_lpm = 6.0

    def step(self, dt: float = 0.1) -> Dict[str, Any]:
        """Runs one simulation step and outputs unified telemetry + predictions."""
        self.tick += 1
        scen = self.DRIVE_SCENARIOS[self.current_scenario]
        
        # Add realistic dynamic variations (throttle oscillations, gear shifts, grades)
        time_s = self.tick * dt
        sine_var = math.sin(time_s * 0.4) * 0.15 + math.sin(time_s * 1.8) * 0.08
        
        torque_demanded = scen["torque_base"] * (1.0 + sine_var)
        torque_demanded = max(10.0, min(350.0, torque_demanded))
        
        speed_rpm = scen["rpm_base"] * (1.0 + sine_var * 0.4)
        speed_rpm = max(500.0, min(11500.0, speed_rpm))

        # FOC direct and quadrature currents
        i_q = torque_demanded * 0.88
        i_d = -40.0 if speed_rpm > 5500 else -5.0

        v_dc = 398.0 - (i_q * 0.04) # DC bus sag under heavy acceleration

        # Step thermal plant
        plant_out = self.plant.step(
            i_d=i_d,
            i_q=i_q,
            speed_rpm=speed_rpm,
            v_dc=v_dc,
            coolant_inlet_temp_C=self.coolant_inlet_temp_C,
            coolant_flow_lpm=self.coolant_flow_lpm,
            dt=dt
        )

        # Run Multi-Horizon Predictor
        predictions = self.predictor.predict(
            current_stator_temp=plant_out["T_stator_winding"],
            current_rotor_temp=plant_out["T_rotor_magnet"],
            current_housing_temp=plant_out["T_housing_frame"],
            i_d=i_d,
            i_q=i_q,
            speed_rpm=speed_rpm,
            coolant_inlet_temp=self.coolant_inlet_temp_C,
            coolant_flow_lpm=self.coolant_flow_lpm,
            projected_load_factor=scen["load_mult"]
        )

        # Pack combined dashboard payload
        speed_kmh = (speed_rpm / 12000.0) * 160.0
        electrical_power_kw = (v_dc * (i_q * 0.707) * 1.732) / 1000.0
        mechanical_power_kw = (torque_demanded * (speed_rpm * 0.1047)) / 1000.0

        return {
            "timestamp_ms": int(time_s * 1000),
            "scenario": {
                "key": self.current_scenario,
                "name": scen["name"],
                "load_multiplier": scen["load_mult"]
            },
            "motor_dynamics": {
                "speed_rpm": round(speed_rpm, 0),
                "speed_kmh": round(speed_kmh, 1),
                "torque_nm": round(torque_demanded, 1),
                "i_d_current_A": round(i_d, 1),
                "i_q_current_A": round(i_q, 1),
                "i_rms_current_A": round(math.sqrt((i_d**2 + i_q**2)/2.0), 1),
                "dc_bus_voltage_V": round(v_dc, 1),
                "electrical_power_kw": round(max(0, electrical_power_kw), 1),
                "mechanical_power_kw": round(max(0, mechanical_power_kw), 1),
                "efficiency_pct": round(min(98.5, max(75.0, (mechanical_power_kw / (electrical_power_kw + 1e-4)) * 100.0)), 1)
            },
            "thermal_live": {
                "stator_winding_temp_C": round(plant_out["T_stator_winding"], 1),
                "stator_core_temp_C": round(plant_out["T_stator_core"], 1),
                "rotor_magnet_temp_C": round(plant_out["T_rotor_magnet"], 1),
                "housing_frame_temp_C": round(plant_out["T_housing_frame"], 1),
                "coolant_inlet_temp_C": round(self.coolant_inlet_temp_C, 1),
                "coolant_flow_lpm": round(self.coolant_flow_lpm, 1),
                "dT_stator_dt_C_per_sec": round(plant_out["dT_stator_dt"], 4),
                "dT_rotor_dt_C_per_sec": round(plant_out["dT_rotor_dt"], 4)
            },
            "losses_watts": {
                "p_copper": round(plant_out["p_copper"], 1),
                "p_iron": round(plant_out["p_iron"], 1),
                "p_mech": round(plant_out["p_mech"], 1),
                "p_rotor_eddy": round(plant_out["p_rotor_eddy"], 1),
                "total_loss": round(plant_out["total_loss"], 1)
            },
            "predictions": predictions
        }
