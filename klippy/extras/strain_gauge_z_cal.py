# Strain Gauge Z Offset Calibration Module
#
# Uses an HX711 load cell sensor at a fixed bed corner pad to calibrate
# the Z offset independently from the main probe (bltouch/crtouch).
# This module does NOT register as 'probe', allowing coexistence with bltouch.
#
# Copyright (C) 2026
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging
import math
import random
from . import hx71x, ads1220, load_cell, load_cell_probe, trigger_analog

CALIBRATION_MOVE_SPEED = 1.0      # mm/s - slow descent speed
CALIBRATION_STEP = 0.05           # mm - step size per iteration
FORCE_THRESHOLD_GRAMS = 20.       # grams of force to detect contact
TARE_SAMPLES = 40                 # number of samples for tare averaging
CONTACT_CONFIRM_SAMPLES = 5       # consecutive samples above threshold
RETRACT_DIST = 2.0                # mm to retract after contact
CLEARANCE_Z = 10.0                # mm Z hop for safe travel moves


class V3SELoadCellPrimitives(load_cell_probe.LoadCellProbingMove):
    """V3 SE extension of regular Klipper load-cell probing."""

    def _pause_and_tare(self, gcmd):
        collector = self._start_collector()

        num_samples = self._config_helper.get_tare_samples(gcmd)
        results = collector.collect_min(num_samples)
        tare_samples = load_cell_probe.check_sensor_errors(
            results, self._printer)

        if not tare_samples:
            raise self._printer.command_error(
                "No load-cell tare samples received")

        # Match the known-good V3 SE behavior:
        # arithmetic average, then integer tare counts.
        tare_average = (
            sum(float(sample[2]) for sample in tare_samples)
            / float(len(tare_samples))
        )
        tare_counts = int(tare_average)

        self._continuous_tare_filter_helper.update_from_command(gcmd)

        self._load_cell.tare(tare_counts)

        safety_min, safety_max = (
            self._config_helper.get_safety_range(gcmd))
        self._mcu_trigger_analog.set_raw_range(
            safety_min, safety_max)

        gpc = (
            self._config_helper.get_grams_per_count()
            * load_cell_probe.FRAC_GRAMS_CONV
        )

        self._mcu_trigger_analog.get_sos_filter().set_offset_scale(
            -tare_counts, gpc)

        trigger_val = (
            self._config_helper.get_trigger_force_grams(gcmd))
        trigger_frac_grams = int(
            trigger_val * load_cell_probe.FRAC_GRAMS_CONV)

        # Retain generic force triggering for diagnostics when
        # PRTouch is explicitly disabled.
        self._mcu_trigger_analog.set_trigger(
            "abs_ge", trigger_frac_grams)

        # PRTouch uses the same freshly measured probe tare.
        self._mcu_trigger_analog.set_prtouch_tare(tare_counts)

        self._tare_counts = tare_counts

    def probing_move(self, unused_mcu_probe, pos, speed, gcmd):
        if not self._load_cell.is_calibrated():
            raise self._printer.command_error(
                "Load Cell not calibrated")

        self._pause_and_tare(gcmd)

        collector = self._start_collector()
        phoming = self._printer.lookup_object("homing")

        try:
            epos = phoming.probing_move(
                self._mcu_trigger_analog,
                pos,
                speed)
        except Exception:
            collector.stop_collecting()
            raise

        return epos, collector

    def add_stepper(self, stepper):
        self._mcu_trigger_analog.get_dispatch().add_stepper(stepper)

    def get_steppers(self):
        return self._mcu_trigger_analog.get_steppers()


class V3SETappingMoveAdapter:
    """Compatibility for the existing safe native air-test command."""

    def __init__(self, printer, primitives):
        self._printer = printer
        self._primitives = primitives

    def probing_move(self, pos, speed, gcmd):
        epos, collector = self._primitives.probing_move(
            self, pos, speed, gcmd)

        toolhead = self._printer.lookup_object("toolhead")
        toolhead.flush_step_generation()

        move_end = toolhead.get_last_move_time()
        results = collector.collect_until(move_end)

        load_cell_probe.check_sensor_errors(
            results, self._printer)

        return epos, True


class StrainGaugeZCal:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()
        # Pad position on the bed (machine coordinates)
        self.pad_x = config.getfloat('pad_x', 0.)
        self.pad_y = config.getfloat('pad_y', 5.)
        # Z calibration parameters
        self.z_start_height = config.getfloat('z_start_height', 5.)
        self.z_min_position = config.getfloat('z_min_position', -2.)
        self.force_threshold = config.getfloat('force_threshold',
                                               FORCE_THRESHOLD_GRAMS)
        self.step_size = config.getfloat('step_size', CALIBRATION_STEP)
        self.speed = config.getfloat('speed', CALIBRATION_MOVE_SPEED)
        self.retract_dist = config.getfloat('retract_dist', RETRACT_DIST)
        self.clearance_z = config.getfloat('clearance_z', CLEARANCE_Z)
        self.travel_speed = config.getfloat('travel_speed', 80.)

        # Creality PRTouch operating controls.
        #
        # These are deliberately config-driven so V3 SE owners can
        # tune or disable the waveform trigger without editing source.
        self.prtouch_trigger = config.getboolean(
            'prtouch_trigger', False)

        self.prtouch_min_hold = config.getint(
            'prtouch_min_hold', 1000, minval=1)
        self.prtouch_max_hold = config.getint(
            'prtouch_max_hold', 1500, minval=1)

        self.prtouch_cal_min_hold = config.getint(
            'prtouch_cal_min_hold', 1400, minval=1)
        self.prtouch_cal_max_hold = config.getint(
            'prtouch_cal_max_hold', 2000, minval=1)

        if self.prtouch_min_hold >= self.prtouch_max_hold:
            raise config.error(
                "prtouch_min_hold must be less than "
                "prtouch_max_hold")

        if self.prtouch_cal_min_hold >= self.prtouch_cal_max_hold:
            raise config.error(
                "prtouch_cal_min_hold must be less than "
                "prtouch_cal_max_hold")
        # Creality V3 SE [z_compensate] final nozzle-contact correction.
        self.tri_expand_mm = config.getfloat(
            'tri_expand_mm', 0.07, minval=0.0)
        # Target probe section to save z_offset to (usually bltouch)
        self.target_probe_section = config.get('target_probe_section',
                                               'bltouch')
        # Initialize the HX711 sensor and LoadCell (standalone)
        sensors = {}
        sensors.update(hx71x.HX71X_SENSOR_TYPES)
        sensors.update(ads1220.ADS1220_SENSOR_TYPE)
        sensor_class = config.getchoice('sensor_type', sensors)
        self.sensor = sensor_class(config)
        self.load_cell = load_cell.LoadCell(config, self.sensor)

        # Private V3 SE PRTouch stack using regular Klipper APIs.
        # CR Touch remains the global Klipper probe.
        self._native_config_helper = (
            load_cell_probe.LoadCellProbeConfigHelper(
                config, self.load_cell))

        self._native_mcu_probe = (
            trigger_analog.MCU_trigger_analog(
                self.sensor))

        cmd_queue = (
            self._native_mcu_probe
            .get_dispatch()
            .get_command_queue()
        )

        sos_filter = trigger_analog.MCU_SosFilter(
            self.sensor.get_mcu(),
            cmd_queue,
            4)

        self._native_mcu_probe.setup_sos_filter(
            sos_filter)

        self._native_tare_filter = (
            load_cell_probe.ContinuousTareFilterHelper(
                config,
                self.sensor,
                sos_filter))

        self._native_primitives = (
            V3SELoadCellPrimitives(
                config,
                self.load_cell,
                self._native_mcu_probe,
                None,
                self._native_tare_filter,
                self._native_config_helper))

        self._native_tapping_move = (
            V3SETappingMoveAdapter(
                self.printer,
                self._native_primitives))

        # Configure the PRTouch algorithm from printer.cfg.
        self._native_mcu_probe.set_prtouch(
            self.prtouch_trigger,
            self.prtouch_min_hold,
            self.prtouch_max_hold)

        # Retain the regular Klipper no-motion tap test.
        load_cell_probe.LoadCellProbeCommands(
            config, self._native_primitives)

        # Register gcode commands
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command(
            'STRAIN_GAUGE_AUTO_Z', self.cmd_STRAIN_GAUGE_AUTO_Z,
            desc="Run complete V3 SE PRTouch automatic Z calibration")
        self.gcode.register_command(
            'STRAIN_GAUGE_CALIBRATE_Z', self.cmd_CALIBRAR_Z_OFFSET,
            desc="Calibrate Z offset using strain gauge at bed corner pad")
        self.gcode.register_command(
            'STRAIN_GAUGE_TARE', self.cmd_STRAIN_GAUGE_TARE,
            desc="Tare the strain gauge sensor")
        self.gcode.register_command(
            'STRAIN_GAUGE_READ', self.cmd_STRAIN_GAUGE_READ,
            desc="Read current strain gauge force")
        self.gcode.register_command(
            'STRAIN_GAUGE_NATIVE_AIR_TEST',
            self.cmd_STRAIN_GAUGE_NATIVE_AIR_TEST,
            desc="Test native MCU strain trigger safely above the bed")
        self.gcode.register_command(
            'STRAIN_GAUGE_NATIVE_STATUS',
            self.cmd_STRAIN_GAUGE_NATIVE_STATUS,
            desc="Report native MCU strain probe stepper attachment")
        self.gcode.register_command(
            'STRAIN_GAUGE_NATIVE_CONTACT_TEST',
            self.cmd_STRAIN_GAUGE_NATIVE_CONTACT_TEST,
            desc="Test native MCU nozzle contact on strain pad")
        self.gcode.register_command(
            'STRAIN_GAUGE_NATIVE_BENCHMARK',
            self.cmd_STRAIN_GAUGE_NATIVE_BENCHMARK,
            desc="Benchmark native MCU strain contact across probe speeds")
        self.gcode.register_command(
            'STRAIN_GAUGE_PRT_THRESHOLD_BENCHMARK',
            self.cmd_STRAIN_GAUGE_PRT_THRESHOLD_BENCHMARK,
            desc="A/B benchmark Creality PRTouch trigger thresholds")
        self.gcode.register_command(
            'STRAIN_GAUGE_NOZZLE_PREP',
            self.cmd_STRAIN_GAUGE_NOZZLE_PREP,
            desc="Prepare and clean nozzle for strain Z calibration")
        logging.info("strain_gauge_z_cal: initialized (pad at X=%.1f Y=%.1f)"
                     % (self.pad_x, self.pad_y))

    def _get_toolhead(self):
        return self.printer.lookup_object('toolhead')

    def _check_homed(self):
        toolhead = self._get_toolhead()
        curtime = self.printer.get_reactor().monotonic()
        kin_status = toolhead.get_kinematics().get_status(curtime)
        if 'x' not in kin_status['homed_axes'] or \
           'y' not in kin_status['homed_axes'] or \
           'z' not in kin_status['homed_axes']:
            return False
        return True

    def _fresh_avg_counts(self, num_samples):
        """Average only load-cell samples captured after this call begins."""
        collector = self.load_cell.get_collector()
        reactor = self.printer.get_reactor()
        mcu = self.sensor.get_mcu()

        min_time = mcu.estimated_print_time(reactor.monotonic())
        collector.start_collecting(min_time=min_time)
        samples, errors = collector.collect_min(num_samples)

        if errors:
            raise self.printer.command_error(
                "Sensor reported %i errors while sampling"
                % (errors[0] + errors[1]))

        if not samples:
            raise self.printer.command_error(
                "No fresh strain-gauge samples received")

        return sum(sample[2] for sample in samples) / float(len(samples))

    def _tare_sensor(self, gcmd):
        """Tare the load cell using only newly captured sensor samples."""
        gcmd.respond_info("Taring strain gauge sensor...")
        try:
            tare_counts = self._fresh_avg_counts(TARE_SAMPLES)
        except Exception as e:
            raise gcmd.error("Tare failed: %s" % str(e))
        self.load_cell.tare(tare_counts)
        pct = self.load_cell.counts_to_percent(tare_counts)
        gcmd.respond_info("Tare complete: counts=%d (%.2f%%)" %
                          (int(tare_counts), pct))
        return tare_counts

    def _read_force_grams(self):
        """Read force using only samples captured after this read begins."""
        if not self.load_cell.is_calibrated():
            return None
        if not self.load_cell.is_tared():
            return None
        try:
            counts = self._fresh_avg_counts(5)
            return self.load_cell.counts_to_grams(counts)
        except Exception:
            return None

    def _probe_z_with_force(self, gcmd):
        """Two-stage strain-gauge Z probing.

        1. Descend quickly using configured step_size to locate contact.
        2. Back off, unload, and establish a local fine-probe baseline.
        3. Descend at 0.01mm resolution for the final contact measurement.
        4. Confirm contact with repeated force readings at the SAME Z.
        """
        toolhead = self._get_toolhead()
        reactor = self.printer.get_reactor()

        coarse_step = self.step_size
        fine_step = min(0.01, coarse_step)
        backoff = max(0.50, coarse_step * 10.0)

        gcmd.respond_info(
            "Starting two-stage Z probe "
            "(threshold=%.1fg, coarse=%.3fmm, fine=%.3fmm)..."
            % (self.force_threshold, coarse_step, fine_step))

        # --------------------------------------------------------------
        # Stage 1: fast coarse search
        # --------------------------------------------------------------
        while True:
            curpos = toolhead.get_position()

            if curpos[2] <= self.z_min_position:
                raise gcmd.error(
                    "Z min position (%.2f) reached without contact!"
                    % self.z_min_position)

            next_z = curpos[2] - coarse_step
            toolhead.manual_move([None, None, next_z], self.speed)
            toolhead.wait_moves()

            reactor.pause(reactor.monotonic() + 0.05)

            force = self._read_force_grams()
            if force is None:
                continue

            if abs(force) >= self.force_threshold:
                coarse_contact_z = toolhead.get_position()[2]
                gcmd.respond_info(
                    "Coarse contact found: Force=%.1fg at Z=%.4f"
                    % (force, coarse_contact_z))
                break

        # --------------------------------------------------------------
        # Back away far enough for the bed/strain gauge to fully unload.
        # Keep the ORIGINAL tare taken before probing. Retaring near
        # contact can zero-out residual mechanical load and shift the
        # detected contact point.
        # --------------------------------------------------------------
        fine_start_z = coarse_contact_z + backoff

        gcmd.respond_info(
            "Backing off %.3fmm to Z=%.4f for fine probe..."
            % (backoff, fine_start_z))

        toolhead.manual_move([None, None, fine_start_z], self.speed)
        toolhead.wait_moves()

        gcmd.respond_info(
            "Allowing strain gauge to relax; preserving original tare...")
        reactor.pause(reactor.monotonic() + 0.50)

        # Measure the local unloaded baseline for this fine pass.
        # Do not retare the sensor. Subtract this small drift only from
        # the fine-probe force measurements.
        fine_baseline = self._read_force_grams()
        if fine_baseline is None:
            raise gcmd.error(
                "Could not establish fine-probe strain baseline")

        gcmd.respond_info(
            "Fine-probe local baseline: %.2fg"
            % fine_baseline)

        # --------------------------------------------------------------
        # Stage 2: fine search
        # --------------------------------------------------------------
        gcmd.respond_info(
            "Starting fine Z probe (step=%.3fmm)..."
            % fine_step)

        # Diagnostic force-vs-Z history. This does not change detection.
        fine_trace = []

        while True:
            curpos = toolhead.get_position()

            if curpos[2] <= self.z_min_position:
                raise gcmd.error(
                    "Z min position (%.2f) reached without contact!"
                    % self.z_min_position)

            next_z = curpos[2] - fine_step
            toolhead.manual_move([None, None, next_z], self.speed)
            toolhead.wait_moves()

            reactor.pause(reactor.monotonic() + 0.05)

            raw_force = self._read_force_grams()
            if raw_force is None:
                continue

            force = raw_force - fine_baseline

            fine_trace.append((toolhead.get_position()[2], force))
            if len(fine_trace) > 40:
                fine_trace.pop(0)

            if abs(force) < self.force_threshold:
                continue

            # Confirm contact without moving Z any farther.
            # The previous implementation moved another full step for
            # every confirmation sample, which added systematic overshoot.
            confirmed = 1
            confirm_force = force

            for _ in range(CONTACT_CONFIRM_SAMPLES - 1):
                reactor.pause(reactor.monotonic() + 0.05)

                raw_confirm_force = self._read_force_grams()
                if raw_confirm_force is None:
                    confirmed = 0
                    break

                confirm_force = (
                    raw_confirm_force - fine_baseline
                )

                if abs(confirm_force) < self.force_threshold:
                    confirmed = 0
                    break

                confirmed += 1

            if confirmed >= CONTACT_CONFIRM_SAMPLES:
                measured_z = toolhead.get_position()[2]
                contact_z = measured_z

                # Interpolate the configured force-threshold crossing
                # between the last below-threshold sample and the first
                # above-threshold sample. This removes the fine-step
                # quantization from the final contact estimate.
                if len(fine_trace) >= 2:
                    prev_z, prev_force = fine_trace[-2]
                    prev_mag = abs(prev_force)
                    cur_mag = abs(force)

                    if (prev_mag < self.force_threshold and
                            cur_mag > prev_mag):
                        fraction = (
                            (self.force_threshold - prev_mag) /
                            (cur_mag - prev_mag)
                        )
                        fraction = max(0.0, min(1.0, fraction))
                        contact_z = (
                            prev_z +
                            fraction * (measured_z - prev_z)
                        )

                gcmd.respond_info(
                    "Fine contact detected! Force=%.1fg\n"
                    "  measured step Z=%.4f\n"
                    "  interpolated threshold Z=%.5f"
                    % (confirm_force, measured_z, contact_z))

                trace_lines = [
                    "  Z=%8.4f  force=%8.2fg" % (z, f)
                    for z, f in fine_trace
                ]
                gcmd.respond_info(
                    "Fine force trace (oldest -> newest):\n%s"
                    % "\n".join(trace_lines))
                return contact_z

    def cmd_STRAIN_GAUGE_AUTO_Z(self, gcmd):
        analyze_only = gcmd.get_int(
            "ANALYZE_ONLY", 0, minval=0, maxval=1)

        if not self.prtouch_trigger:
            raise gcmd.error(
                "V3 SE Auto-Z requires PRTouch waveform triggering. "
                "Set prtouch_trigger: True to enable Auto-Z.")

        # AUTO Z owns the complete linked V3 SE Z-compensation transaction.
        # The individual nozzle-prep and calibration commands remain
        # independently callable for diagnostics and development.
        reactor = self.printer.get_reactor()
        eventtime = reactor.monotonic()
        gcode = self.gcode

        # Do not allow an automatic calibration to begin during a print or
        # while a print is paused.
        print_stats = self.printer.lookup_object('print_stats', None)
        if print_stats is not None:
            print_state = (
                print_stats.get_status(eventtime)
                .get('state', '')
                .lower())
            if print_state in ('printing', 'paused'):
                raise gcmd.error(
                    "STRAIN_GAUGE_AUTO_Z cannot run while a print is %s"
                    % print_state)

        # Preserve the active mesh once for the entire linked routine.
        # AUTO Z clears it before any homing/contact work and restores it
        # only after the complete sequence finishes.
        bed_mesh = self.printer.lookup_object('bed_mesh', None)
        mesh_was_active = False
        active_profile = ""

        if bed_mesh is not None:
            mesh_status = bed_mesh.get_status(eventtime)
            active_profile = mesh_status.get('profile_name', '')
            mesh_matrix = mesh_status.get('mesh_matrix', [[]])
            mesh_was_active = bool(mesh_matrix and mesh_matrix[0])

            if mesh_was_active and not active_profile:
                raise gcmd.error(
                    "Active bed mesh has no saved profile name. "
                    "Load a saved mesh profile before running AUTO Z.")

        # Preserve heater targets so a failed AUTO Z can return the printer
        # to the thermal state it had before the command started.
        extruder = self.printer.lookup_object('extruder', None)
        heater_bed = self.printer.lookup_object('heater_bed', None)

        initial_extruder_target = 0.0
        initial_bed_target = 0.0

        if extruder is not None:
            initial_extruder_target = (
                extruder.get_status(eventtime).get('target', 0.0))

        if heater_bed is not None:
            initial_bed_target = (
                heater_bed.get_status(eventtime).get('target', 0.0))

        # Creality V3 SE Z compensation uses 1400/2000 for the complete
        # Z-compensation process, not only the final two-point measurement.
        cal_prtouch_min_hold = gcmd.get_int(
            "PRTOUCH_MIN_HOLD", self.prtouch_cal_min_hold, minval=1)
        cal_prtouch_max_hold = gcmd.get_int(
            "PRTOUCH_MAX_HOLD", self.prtouch_cal_max_hold, minval=1)

        if cal_prtouch_min_hold >= cal_prtouch_max_hold:
            raise gcmd.error(
                "PRTOUCH_MIN_HOLD must be less than PRTouch max hold")

        normal_prtouch_min_hold, normal_prtouch_max_hold = (
            self._native_mcu_probe.get_prtouch_thresholds()
        )

        prtouch_thresholds_switched = False
        auto_z_complete = False

        gcmd.respond_info(
            "=== V3 SE AUTOMATIC Z CALIBRATION ===\n"
            "Linked factory sequence enabled\n"
            "Mesh: preserve -> clear -> restore once\n"
            "PRTouch Z-comp thresholds: min=%d max=%d\n"
            "ANALYZE_ONLY=%d"
            % (
                cal_prtouch_min_hold,
                cal_prtouch_max_hold,
                analyze_only,
            ))

        try:
            # Establish one mesh-free coordinate system for the complete
            # factory-style sequence.
            if mesh_was_active:
                gcmd.respond_info(
                    "AUTO Z: clearing bed mesh profile '%s'..."
                    % active_profile)
                gcode.run_script_from_command("BED_MESH_CLEAR")

            # Start from a known fully homed machine state.
            gcmd.respond_info(
                "AUTO Z: homing printer before nozzle preparation...")
            gcode.run_script_from_command("G28")

            # Keep the stronger Z-compensation PRTouch thresholds active
            # continuously through nozzle prep and final calibration.
            if not self._native_mcu_probe.set_prtouch_thresholds(
                    cal_prtouch_min_hold,
                    cal_prtouch_max_hold):
                raise gcmd.error(
                    "PRTouch waveform triggering is not enabled")

            prtouch_thresholds_switched = True

            gcmd.respond_info(
                "AUTO Z: PRTouch thresholds active: min=%d max=%d"
                % (
                    cal_prtouch_min_hold,
                    cal_prtouch_max_hold,
                ))

            # Complete factory thermal/nozzle preparation.  Because AUTO Z
            # already cleared the mesh, the standalone helper does not
            # independently restore a mesh in the middle of the sequence.
            self._run_nozzle_prep(gcmd)

            # _run_nozzle_prep() finishes at the factory 140C / 60C state
            # and performs the final G28 Z.  Immediately continue into the
            # two-point CR Touch + PRTouch measurement while that state is
            # still intact.
            gcmd.respond_info(
                "AUTO Z: nozzle preparation complete; "
                "starting linked two-point calibration...")

            self._run_z_calibration(gcmd)

            auto_z_complete = True

            if analyze_only:
                gcmd.respond_info(
                    "=== AUTO Z ANALYSIS COMPLETE ===\n"
                    "The complete linked routine ran successfully.\n"
                    "No Z offset was staged or changed.")
            else:
                gcmd.respond_info(
                    "=== AUTO Z COMPLETE ===\n"
                    "The calculated Z offset is applied live and staged "
                    "in the configuration.\n"
                    "Verify the result, then run SAVE_CONFIG to make it "
                    "permanent.")

        finally:
            # Restore the normal PRTouch thresholds exactly once after the
            # complete linked transaction.
            if prtouch_thresholds_switched:
                try:
                    self._native_mcu_probe.set_prtouch_thresholds(
                        normal_prtouch_min_hold,
                        normal_prtouch_max_hold)
                    gcmd.respond_info(
                        "AUTO Z: restored normal PRTouch thresholds: "
                        "min=%d max=%d"
                        % (
                            normal_prtouch_min_hold,
                            normal_prtouch_max_hold,
                        ))
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: AUTO Z could not restore normal PRTouch "
                        "thresholds: %s" % str(e))

            # Restore the mesh that was active before AUTO Z.  The mesh is
            # deliberately not regenerated by Z calibration.
            if mesh_was_active and active_profile:
                try:
                    gcmd.respond_info(
                        "AUTO Z: restoring bed mesh profile '%s'..."
                        % active_profile)
                    gcode.run_script_from_command(
                        'BED_MESH_PROFILE LOAD="%s"' % active_profile)
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: AUTO Z could not restore bed mesh '%s': %s"
                        % (active_profile, str(e)))

            # On failure, leave the machine thermally safe and return heater
            # targets to their pre-AUTO-Z state.  A successful AUTO Z keeps
            # the factory completion state of 140C nozzle / 60C bed.
            if not auto_z_complete:
                try:
                    gcode.run_script_from_command("M106 S0")
                except Exception:
                    pass

                try:
                    gcode.run_script_from_command(
                        "M104 S%.1f" % initial_extruder_target)
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: AUTO Z could not restore nozzle target: %s"
                        % str(e))

                try:
                    gcode.run_script_from_command(
                        "M140 S%.1f" % initial_bed_target)
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: AUTO Z could not restore bed target: %s"
                        % str(e))

    cmd_CALIBRAR_Z_OFFSET_help = ("Calibrate Z offset using strain gauge "
                                  "at bed corner pad")
    def cmd_CALIBRAR_Z_OFFSET(self, gcmd):
        return self._run_z_calibration(gcmd)

    def _run_z_calibration(self, gcmd):
        analyze_only = gcmd.get_int('ANALYZE_ONLY', 0, minval=0, maxval=1)
        # Calibrate BLTouch/CR Touch Z offset using the V3 SE strain gauge.
        #
        # The CR Touch and nozzle must measure the SAME physical bed point.
        # The active bed mesh is temporarily cleared so it cannot alter
        # the calibration coordinate system.

        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()
        gcode = self.printer.lookup_object('gcode')
        reactor = self.printer.get_reactor()

        # Preserve any existing live G-code Z offset.  Creality performs
        # Z compensation from a zero temporary offset, so calibration must
        # not inherit a previous SET_GCODE_OFFSET adjustment.
        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move_status = gcode_move.get_status(reactor.monotonic())
        original_live_z_offset = gcode_move_status['homing_origin'].z
        live_offset_reset = False
        keep_calibrated_live_offset = False

        probe = self.printer.lookup_object('probe')
        current_offsets = probe.get_offsets()
        x_offset = current_offsets[0]
        y_offset = current_offsets[1]
        current_z_offset = current_offsets[2]

        # The configured pad_x/pad_y are the physical center of the
        # V3 SE Z-compensation strain-gauge area.  Calibration measures
        # two symmetric physical points around this center.
        #
        # For any physical nozzle point:
        #   CR Touch carriage X = physical X - probe X offset
        #   CR Touch carriage Y = physical Y - probe Y offset

        # Remember active mesh so we can restore it after calibration.
        bed_mesh = self.printer.lookup_object('bed_mesh', None)
        mesh_was_active = False
        active_profile = ""

        # Creality V3 SE uses stronger PRTouch waveform thresholds during
        # Z compensation than during normal PRTouch operation.
        cal_prtouch_min_hold = gcmd.get_int(
            "PRTOUCH_MIN_HOLD", self.prtouch_cal_min_hold, minval=1)
        cal_prtouch_max_hold = gcmd.get_int(
            "PRTOUCH_MAX_HOLD", self.prtouch_cal_max_hold, minval=1)

        if cal_prtouch_min_hold >= cal_prtouch_max_hold:
            raise gcmd.error(
                "PRTOUCH_MIN_HOLD must be less than PRTouch max hold")

        normal_prtouch_min_hold, normal_prtouch_max_hold = (
            self._native_mcu_probe.get_prtouch_thresholds()
        )
        prtouch_thresholds_switched = False

        if bed_mesh is not None:
            mesh_status = bed_mesh.get_status(reactor.monotonic())
            active_profile = mesh_status.get('profile_name', '')
            mesh_matrix = mesh_status.get('mesh_matrix', [[]])
            mesh_was_active = bool(mesh_matrix and mesh_matrix[0])

            if mesh_was_active and not active_profile:
                raise gcmd.error(
                    "Active bed mesh has no saved profile name. "
                    "Load a saved mesh profile before running calibration.")

        gcmd.respond_info(
            "=== Z OFFSET CALIBRATION (CR Touch + PRTouch) ===\n"
            "Z-compensation center: X=%.2f Y=%.2f\n"
            "CR Touch offset: X=%.2f Y=%.2f"
            % (
                self.pad_x,
                self.pad_y,
                x_offset,
                y_offset,
            ))

        try:
            # Match Creality Z-compensation semantics: perform the
            # measurement with no temporary G-code Z transform active.
            gcode.run_script_from_command(
                'SET_GCODE_OFFSET Z=0 MOVE=0')
            live_offset_reset = True
            gcmd.respond_info(
                "Temporarily reset live Z offset: %.5f -> 0.00000"
                % original_live_z_offset)

            if not self._native_mcu_probe.set_prtouch_thresholds(
                    cal_prtouch_min_hold,
                    cal_prtouch_max_hold):
                raise gcmd.error(
                    "PRTouch waveform triggering is not enabled")

            prtouch_thresholds_switched = True

            gcmd.respond_info(
                "Calibration PRTouch thresholds: min=%d max=%d"
                % (
                    cal_prtouch_min_hold,
                    cal_prtouch_max_hold,
                )
            )

            # Remove mesh compensation during ALL calibration measurements.
            if mesh_was_active:
                gcmd.respond_info(
                    "Temporarily clearing bed mesh profile '%s'..."
                    % active_profile)
                gcode.run_script_from_command("BED_MESH_CLEAR")

            # ----------------------------------------------------------
            # Creality-style two-point Z compensation.
            #
            # Recovered V3 SE configuration uses two symmetric physical
            # points around the center, with X/Y expansion in the 3..7 mm
            # range.  Explicit POINT_DX / POINT_DY may be supplied for
            # repeatable diagnostic testing.
            # ----------------------------------------------------------
            point_dx = gcmd.get_float(
                "POINT_DX",
                random.uniform(3.0, 7.0),
                minval=3.0,
                maxval=7.0)
            point_dy = gcmd.get_float(
                "POINT_DY",
                random.uniform(3.0, 7.0),
                minval=3.0,
                maxval=7.0)

            calibration_points = [
                (
                    "POINT1",
                    self.pad_x + point_dx,
                    self.pad_y + point_dy,
                ),
                (
                    "POINT2",
                    self.pad_x - point_dx,
                    self.pad_y - point_dy,
                ),
            ]

            gcmd.respond_info(
                "Z-compensation point expansion: "
                "DX=%.3f DY=%.3f mm"
                % (point_dx, point_dy))

            native_speed = gcmd.get_float(
                "NATIVE_SPEED", 1.00, above=0.0)
            search_end_z = gcmd.get_float(
                "SEARCH_END_Z", 0.0, minval=-0.5, maxval=0.3)

            # trigger_force is retained only for diagnostic reconstruction
            # of the raw force crossing.  With PRTouch enabled it is not an
            # MCU motion trigger.
            trigger_force = (
                self._native_config_helper.get_trigger_force_grams(gcmd))

            # Calibration-local CR Touch sampling.  Normal [bltouch]
            # configuration remains unchanged.
            probe_params = gcmd.get_command_parameters()
            probe_params.setdefault("SAMPLES", "3")
            probe_params.setdefault("SAMPLES_RESULT", "median")

            gcmd.respond_info(
                "Calibration CR Touch sampling: SAMPLES=%s RESULT=%s"
                % (
                    probe_params["SAMPLES"],
                    probe_params["SAMPLES_RESULT"],
                ))

            point_results = []

            for point_index, (point_label, physical_x, physical_y) in enumerate(
                    calibration_points, start=1):

                probe_x = physical_x - x_offset
                probe_y = physical_y - y_offset

                gcmd.respond_info(
                    "=== Z-COMP %s (%d/2) ===\n"
                    "Physical point: X=%.3f Y=%.3f\n"
                    "CR Touch carriage: X=%.3f Y=%.3f"
                    % (
                        point_label,
                        point_index,
                        physical_x,
                        physical_y,
                        probe_x,
                        probe_y,
                    ))

                # ------------------------------------------------------
                # CR Touch: measure this exact physical bed point.
                # ------------------------------------------------------
                curpos = toolhead.get_position()
                safe_z = max(curpos[2], self.clearance_z)
                toolhead.manual_move(
                    [None, None, safe_z], 10.0)
                toolhead.wait_moves()

                toolhead.manual_move(
                    [probe_x, probe_y, None],
                    self.travel_speed)
                toolhead.wait_moves()

                probe_pos = probe.run_probe(gcmd)

                if probe_pos is None or len(probe_pos) < 3:
                    raise gcmd.error(
                        "CR Touch did not return a valid result at %s"
                        % point_label)

                cr_touch_z = probe_pos[2]

                gcmd.respond_info(
                    "%s CR Touch median Z=%.5f"
                    % (point_label, cr_touch_z))

                # Retract before moving the nozzle onto the same point.
                curpos = toolhead.get_position()
                retract_z = max(
                    curpos[2] + self.retract_dist,
                    self.clearance_z)
                toolhead.manual_move(
                    [None, None, retract_z], 10.0)
                toolhead.wait_moves()

                # ------------------------------------------------------
                # PRTouch nozzle contact: 3 contacts, median trigger Z.
                # ------------------------------------------------------
                toolhead.manual_move(
                    [physical_x, physical_y, None],
                    self.travel_speed)
                toolhead.wait_moves()

                trigger_contacts = []
                event_contacts = []
                raw_crossings = []

                for pass_index in range(3):
                    gcmd.respond_info(
                        "=== %s PRTouch PASS %d/3 ==="
                        % (point_label, pass_index + 1))

                    toolhead.manual_move(
                        [None, None, 3.0], 5.0)
                    toolhead.wait_moves()

                    pos = toolhead.get_position()
                    pos[2] = search_end_z

                    epos, collector = (
                        self._native_primitives.probing_move(
                            self._native_tapping_move,
                            pos,
                            native_speed,
                            gcmd))

                    toolhead.flush_step_generation()
                    move_end = toolhead.get_last_move_time()

                    collected = collector.collect_until(move_end)
                    samples = load_cell_probe.check_sensor_errors(
                        collected, self.printer)

                    trigger_z = epos[2]

                    eventtime = reactor.monotonic()
                    trigger_time = (
                        self._native_primitives.get_status(
                            eventtime)["last_trigger_time"])

                    trigger_source = (
                        self._native_mcu_probe.get_last_trigger_source())

                    if trigger_source != 1:
                        raise gcmd.error(
                            "%s pass %d did not trigger from PRTouch "
                            "(source=%d)"
                            % (
                                point_label,
                                pass_index + 1,
                                trigger_source,
                            ))

                    threshold_z, onset_z, fit_count = (
                        self._analyze_native_contact_samples(
                            samples,
                            trigger_time,
                            trigger_z,
                            native_speed,
                            trigger_force))

                    # Use the exact 32-sample MCU PRTouch FIFO that
                    # caused this trigger.  This replaces the former
                    # approximation of selecting the last 32 samples
                    # from Kalico's general host collector.
                    creality_samples = (
                        self._native_mcu_probe
                        .get_last_prtouch_snapshot()
                    )

                    if len(creality_samples) != 32:
                        creality_event_z = None
                        creality_event_count = len(
                            creality_samples)
                        creality_event_index = None
                        creality_before_ms = None

                        gcmd.respond_info(
                            "%s pass %d/3: frozen MCU PRTouch "
                            "FIFO unavailable/incomplete "
                            "(samples=%d, expected=32)"
                            % (
                                point_label,
                                pass_index + 1,
                                len(creality_samples),
                            ))
                    else:
                        (
                            creality_event_z,
                            creality_event_count,
                            creality_event_index,
                            creality_before_ms,
                        ) = self._analyze_creality_contact_event(
                            creality_samples,
                            trigger_time,
                            trigger_z,
                            native_speed)

                    trigger_contacts.append(trigger_z)

                    if creality_event_z is not None:
                        event_contacts.append(creality_event_z)

                    if threshold_z is not None:
                        raw_crossings.append(threshold_z)

                    gcmd.respond_info(
                        "%s pass %d/3:\n"
                        "  MCU PRTouch trigger Z=%.5f\n"
                        "  source=%d(prtouch)\n"
                        "  Creality event Z=%s\n"
                        "  event index=%s before trigger=%s\n"
                        "  raw %.1fg crossing Z=%s\n"
                        "  onset estimate Z=%s"
                        % (
                            point_label,
                            pass_index + 1,
                            trigger_z,
                            trigger_source,
                            ("%.5f" % creality_event_z)
                            if creality_event_z is not None else "N/A",
                            str(creality_event_index)
                            if creality_event_index is not None else "N/A",
                            ("%.1fms" % creality_before_ms)
                            if creality_before_ms is not None else "N/A",
                            trigger_force,
                            ("%.5f" % threshold_z)
                            if threshold_z is not None else "N/A",
                            ("%.5f" % onset_z)
                            if onset_z is not None else "N/A",
                        ))

                    toolhead.manual_move(
                        [None, None, 3.0], 5.0)
                    toolhead.wait_moves()

                sorted_triggers = sorted(trigger_contacts)
                nozzle_trigger_z = sorted_triggers[1]

                point_offset = cr_touch_z - nozzle_trigger_z

                event_median_z = None
                event_offset = None

                if len(event_contacts) == 3:
                    sorted_events = sorted(event_contacts)
                    event_median_z = sorted_events[1]
                    event_offset = cr_touch_z - event_median_z

                point_results.append({
                    "label": point_label,
                    "physical_x": physical_x,
                    "physical_y": physical_y,
                    "cr_touch_z": cr_touch_z,
                    "trigger_contacts": trigger_contacts,
                    "nozzle_trigger_z": nozzle_trigger_z,
                    "event_contacts": event_contacts,
                    "event_median_z": event_median_z,
                    "event_offset": event_offset,
                    "raw_crossings": raw_crossings,
                    "offset": point_offset,
                })

                gcmd.respond_info(
                    "%s RESULT:\n"
                    "  CR Touch Z=%.5f\n"
                    "  PRTouch triggers: %.5f / %.5f / %.5f\n"
                    "  PRTouch median Z=%.5f\n"
                    "  point offset=%.5f"
                    % (
                        point_label,
                        cr_touch_z,
                        trigger_contacts[0],
                        trigger_contacts[1],
                        trigger_contacts[2],
                        nozzle_trigger_z,
                        point_offset,
                    ))

                if event_median_z is None:
                    gcmd.respond_info(
                        "%s Creality-event diagnostic: unavailable"
                        % point_label)
                else:
                    gcmd.respond_info(
                        "%s CREALITY-EVENT DIAGNOSTIC:\n"
                        "  event Z values: %.5f / %.5f / %.5f\n"
                        "  event median Z=%.5f\n"
                        "  event-derived point offset=%.5f"
                        % (
                            point_label,
                            event_contacts[0],
                            event_contacts[1],
                            event_contacts[2],
                            event_median_z,
                            event_offset,
                        ))

            if len(point_results) != 2:
                raise gcmd.error(
                    "Two-point Z compensation did not complete")

            # Keep the MCU trigger result as a diagnostic only.
            trigger_offset_1 = point_results[0]["offset"]
            trigger_offset_2 = point_results[1]["offset"]
            trigger_combined = (
                trigger_offset_1 + trigger_offset_2
            ) / 2.0

            # Production Z compensation uses the reconstructed Creality
            # waveform-event coordinate, matching cal_tri_data semantics.
            event_offset_1 = point_results[0]["event_offset"]
            event_offset_2 = point_results[1]["event_offset"]

            if event_offset_1 is None or event_offset_2 is None:
                raise gcmd.error(
                    "Creality waveform event unavailable. "
                    "Calibration rejected; MCU trigger fallback is disabled.")

            event_combined = (
                event_offset_1 + event_offset_2
            ) / 2.0

            # Creality factory final math:
            # average(two physical point offsets) - tri_expand_mm.
            new_z_offset = event_combined - self.tri_expand_mm

            if new_z_offset < 0.:
                raise gcmd.error(
                    "Calculated z_offset is negative (%.4f). "
                    "Calibration rejected."
                    % new_z_offset)

            gcmd.respond_info(
                "=== TWO-POINT Z-COMP CALIBRATION RESULT ===\n"
                "POINT1 event offset: %.5f\n"
                "POINT2 event offset: %.5f\n"
                "Event point difference: %.5f\n"
                "Event combined average: %.5f\n"
                "tri_expand_mm: %.5f\n"
                "Previous Z offset: %.5f\n"
                "Proposed Z offset: %.5f\n"
                "MCU trigger diagnostic average: %.5f"
                % (
                    event_offset_1,
                    event_offset_2,
                    abs(event_offset_1 - event_offset_2),
                    event_combined,
                    self.tri_expand_mm,
                    current_z_offset,
                    new_z_offset,
                    trigger_combined,
                ))

            if analyze_only:
                gcmd.respond_info(
                    "ANALYZE_ONLY=1: Z offset was NOT staged or changed.\n"
                    "=== CALIBRATION ANALYSIS COMPLETE ===")
            else:
                # Creality factory behavior:
                #   live adjustment = old configured probe offset
                #                     - newly calculated probe offset
                #
                # The live G-code offset was reset to zero above, so this
                # applies the calculated correction exactly once.
                live_z_adjust = current_z_offset - new_z_offset
                gcode.run_script_from_command(
                    'SET_GCODE_OFFSET Z_ADJUST=%.6f MOVE=1'
                    % live_z_adjust)

                configfile = self.printer.lookup_object('configfile')
                configfile.set(
                    self.target_probe_section,
                    'z_offset',
                    "%.3f" % new_z_offset)

                # Calibration succeeded and the new live adjustment is now
                # intentional.  Do not restore the pre-calibration offset.
                keep_calibrated_live_offset = True

                gcmd.respond_info(
                    "Applied live Z compensation: %.5f "
                    "(%.5f - %.5f)\n"
                    "Z offset staged in config. "
                    "DO NOT run SAVE_CONFIG until the result is verified.\n"
                    "=== CALIBRATION COMPLETE ==="
                    % (
                        live_z_adjust,
                        current_z_offset,
                        new_z_offset,
                    ))

        finally:
            # ANALYZE_ONLY and failed calibrations must leave the printer's
            # previous live Z state exactly as it was before calibration.
            if live_offset_reset and not keep_calibrated_live_offset:
                try:
                    gcode.run_script_from_command(
                        'SET_GCODE_OFFSET Z=%.6f MOVE=0'
                        % original_live_z_offset)
                    gcmd.respond_info(
                        "Restored previous live Z offset: %.5f"
                        % original_live_z_offset)
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: Could not restore previous live Z "
                        "offset: %s" % str(e))

            if prtouch_thresholds_switched:
                try:
                    self._native_mcu_probe.set_prtouch_thresholds(
                        normal_prtouch_min_hold,
                        normal_prtouch_max_hold)
                    gcmd.respond_info(
                        "Restored normal PRTouch thresholds: min=%d max=%d"
                        % (
                            normal_prtouch_min_hold,
                            normal_prtouch_max_hold,
                        )
                    )
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: Could not restore normal PRTouch "
                        "thresholds: %s" % str(e))

            if mesh_was_active and active_profile:
                try:
                    gcmd.respond_info(
                        "Restoring bed mesh profile '%s'..."
                        % active_profile)
                    gcode.run_script_from_command(
                        'BED_MESH_PROFILE LOAD="%s"'
                        % active_profile)
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: Could not restore bed mesh '%s': %s"
                        % (active_profile, str(e)))

    def _analyze_native_contact_samples(
            self, samples, trigger_time, trigger_z, speed, trigger_force):
        mapped = []

        for sample in samples:
            sample_time = sample[0]
            force = sample[1]
            delta_t = trigger_time - sample_time
            sample_z = trigger_z + speed * delta_t

            if abs(delta_t) <= 0.150:
                mapped.append((sample_time, sample_z, force))

        threshold_z = None
        for i in range(1, len(mapped)):
            _, prev_z, prev_force = mapped[i - 1]
            _, cur_z, cur_force = mapped[i]

            prev_mag = abs(prev_force)
            cur_mag = abs(cur_force)

            if (prev_mag < trigger_force <= cur_mag
                    and cur_mag > prev_mag):
                fraction = (
                    (trigger_force - prev_mag) /
                    (cur_mag - prev_mag)
                )
                threshold_z = (
                    prev_z + fraction * (cur_z - prev_z)
                )
                break

        fit_min_force = max(3.0, trigger_force * 0.15)
        fit_max_force = trigger_force * 1.50
        fit_points = []

        for sample_time, sample_z, force in mapped:
            if sample_time > trigger_time:
                continue

            mag = abs(force)
            if fit_min_force <= mag <= fit_max_force:
                fit_points.append((mag, sample_z))

        contact_onset_z = None

        if len(fit_points) >= 2:
            n = float(len(fit_points))
            sx = sum(point[0] for point in fit_points)
            sy = sum(point[1] for point in fit_points)
            sxx = sum(point[0] * point[0] for point in fit_points)
            sxy = sum(point[0] * point[1] for point in fit_points)
            denom = n * sxx - sx * sx

            if abs(denom) > 1.0e-12:
                slope = (n * sxy - sx * sy) / denom
                contact_onset_z = (sy - slope * sx) / n

        return threshold_z, contact_onset_z, len(fit_points)

    def _analyze_creality_contact_event(
            self, samples, trigger_time, trigger_z, speed):
        # Creality PRTouch V2 keeps a rolling 32-sample pressure FIFO
        # and analyzes the final samples leading into its MCU trigger.
        #
        # We reproduce that event-selection concept here using Kalico's
        # timestamped HX711 samples.  This is DIAGNOSTIC ONLY for now.

        pre_trigger = []

        for sample in samples:
            sample_time = sample[0]
            force = sample[1]

            if sample_time <= trigger_time:
                pre_trigger.append((sample_time, force))

        pre_trigger.sort(key=lambda item: item[0])

        if len(pre_trigger) < 8:
            return None, len(pre_trigger), None, None

        # Match Creality MAX_BUF_LEN = 32.
        window = pre_trigger[-32:]

        times = [item[0] for item in window]
        data = [float(item[1]) for item in window]

        # Diagnostic only: preserve the exact raw frozen FIFO so unstable
        # Creality event selections can be reconstructed offline.
        raw_data = list(data)
        logging.info(
            "strain_gauge_z_cal: event raw32 "
            "invert=%s first=%.1f last=%.1f values=%s",
            raw_data[-1] < raw_data[0],
            raw_data[0],
            raw_data[-1],
            ",".join("%.1f" % value for value in raw_data),
        )

        # Creality normalizes non-ADC pressure polarity before
        # cal_tri_data() filtering so the contact ramp always points
        # in the expected direction.
        if data[-1] < data[0]:
            data = [-value for value in data]

        # Creality's non-ADC cal_tri_data() first performs a
        # three-sample minimum-absolute-value selection.
        for i in range(len(data) - 2):
            d3_abs = [
                abs(data[i]),
                abs(data[i + 1]),
                abs(data[i + 2]),
            ]
            offset = d3_abs.index(min(d3_abs))
            data[i] = data[i + offset]

        # Determine the actual Kalico sample interval instead of assuming
        # Creality's nominal 12ms interval.  V3 SE factory default
        # cal_hftr_cut is 10Hz.
        intervals = []

        for i in range(1, len(times)):
            dt = times[i] - times[i - 1]
            if dt > 0.0:
                intervals.append(dt)

        if not intervals:
            return None, len(window), None, None

        intervals.sort()
        sample_dt = intervals[len(intervals) // 2]

        def calc_event_index(filter_dt):
            cal_hftr_cut = 10.0
            rc = 1.0 / (2.0 * math.pi * cal_hftr_cut)
            coff = rc / (rc + filter_dt)

            source = list(data)
            filtered = [0.0]

            for i in range(1, len(source)):
                filtered.append(
                    (source[i] - source[i - 1] + filtered[-1]) * coff)

            # Creality non-ADC default cal_lftr_k1 = 0.85.
            cal_lftr_k1 = 0.85

            for i in range(1, len(filtered)):
                filtered[i] = (
                    filtered[i - 1] * (1.0 - cal_lftr_k1)
                    + filtered[i] * cal_lftr_k1)

            min_val = min(filtered)
            max_val = max(filtered)
            value_range = max_val - min_val

            if abs(value_range) < 1.0e-12:
                return None

            vals = [
                (value - min_val) / value_range
                for value in filtered
            ]

            # Match Creality cal_tri_data() de-trend / rotation.
            angle = math.atan(
                (vals[-1] - vals[0]) / float(len(vals)))

            sin_angle = math.sin(-angle)
            cos_angle = math.cos(-angle)

            detrended = []

            for i, value in enumerate(vals):
                detrended.append(
                    float(i) * sin_angle
                    + value * cos_angle)

            return detrended.index(min(detrended))

        # Preserve current measured-interval behavior.
        event_index = calc_event_index(sample_dt)

        if event_index is None:
            return None, len(window), None, None

        event_time = times[event_index]

        # Diagnostic A/B against Creality factory tri_acq_ms=12.
        factory_event_index = calc_event_index(0.012)

        if factory_event_index is not None:
            factory_event_time = times[factory_event_index]

            logging.info(
                "strain_gauge_z_cal: filter dt A/B "
                "measured_dt=%.3fms measured_index=%d "
                "factory12_index=%d index_delta=%+d "
                "measured_before=%.3fms factory_before=%.3fms "
                "z_delta=%+.6f",
                sample_dt * 1000.0,
                event_index,
                factory_event_index,
                factory_event_index - event_index,
                (trigger_time - event_time) * 1000.0,
                (trigger_time - factory_event_time) * 1000.0,
                speed * (event_time - factory_event_time),
            )

        # Keep the previous constant-speed mapping for comparison.
        constant_speed_z = (
            trigger_z
            + speed * (trigger_time - event_time)
        )
        event_z = constant_speed_z

        # Kalico already retains historical MCU step positions.  Rebuild
        # Cartesian Z at the pressure event and trigger timestamps using
        # the same printer kinematics used by HomingMove.
        try:
            toolhead = self._get_toolhead()
            kin = toolhead.get_kinematics()

            event_spos = {}
            trigger_spos = {}

            for stepper in kin.get_steppers():
                name = stepper.get_name()

                event_mcu = stepper.get_past_mcu_position(event_time)
                trigger_mcu = stepper.get_past_mcu_position(trigger_time)

                event_spos[name] = stepper.mcu_to_commanded_position(
                    event_mcu)
                trigger_spos[name] = stepper.mcu_to_commanded_position(
                    trigger_mcu)

            event_cart = kin.calc_position(event_spos)
            trigger_cart = kin.calc_position(trigger_spos)

            historical_z = (
                trigger_z
                + event_cart[2]
                - trigger_cart[2]
            )

            logging.info(
                "strain_gauge_z_cal: event Z mapping "
                "constant=%.6f historical=%.6f delta=%.6f "
                "event_calc_z=%.6f trigger_calc_z=%.6f",
                constant_speed_z,
                historical_z,
                historical_z - constant_speed_z,
                event_cart[2],
                trigger_cart[2],
            )

            event_z = historical_z

        except Exception:
            logging.exception(
                "strain_gauge_z_cal: historical event Z lookup failed; "
                "using constant-speed mapping"
            )

        before_trigger_ms = (
            (trigger_time - event_time) * 1000.0)

        return (
            event_z,
            len(window),
            event_index,
            before_trigger_ms,
        )

    def _replay_creality_mcu_trigger(
            self, samples, trigger_time, trigger_z, probe_speed):
        # Diagnostic replay of Creality's non-ADC PRTouch MCU trigger.
        #
        # This does NOT control motion.  It replays the factory
        # 32-sample T/H/L filtering and trigger tests against the raw
        # HX711 history collected during the existing Kalico probe.
        #
        # Kalico's current tare is used as the equivalent of Creality's
        # pre-probe tri_avg_vals baseline.

        history = []

        try:
            tare_counts = float(self.load_cell.get_tare_counts())
        except Exception:
            return None

        for sample in samples:
            sample_time = float(sample[0])

            if sample_time > trigger_time:
                continue

            if len(sample) < 3:
                continue

            raw_counts = float(sample[2])
            history.append(
                (sample_time, raw_counts - tare_counts))

        if len(history) < 32:
            return None

        tri_min_hold = float(self.prtouch_min_hold)
        tri_max_hold = float(self.prtouch_max_hold)
        tri_hftr_cut = 2.0
        tri_lftr_k1 = 0.70

        for end_index in range(31, len(history)):
            window = history[end_index - 31:end_index + 1]

            times = [item[0] for item in window]
            data = [item[1] for item in window]

            # Creality polarity normalization.
            if data[-1] < data[0]:
                data = [-value for value in data]

            # Creality T filter:
            # choose the smallest absolute value from each 3-sample group.
            for i in range(0, 30):
                a = data[i]
                b = data[i + 1]
                c = data[i + 2]

                chosen = a if abs(a) < abs(b) else b

                if abs(c) < abs(chosen):
                    chosen = c

                data[i] = chosen

            # Use the actual Kalico/HX711 sample interval.
            intervals = [
                times[i] - times[i - 1]
                for i in range(1, len(times))
                if times[i] > times[i - 1]
            ]

            if intervals:
                intervals.sort()
                sample_dt = intervals[len(intervals) // 2]
            else:
                sample_dt = 0.0125

            # Creality high-pass filter.
            rc = 1.0 / (2.0 * math.pi * tri_hftr_cut)
            coff = rc / (rc + sample_dt)

            filtered = [0.0] * 32

            for i in range(1, 32):
                filtered[i] = (
                    data[i]
                    - data[i - 1]
                    + filtered[i - 1]
                ) * coff

            # Creality recursive low-pass filter.
            for i in range(1, 32):
                filtered[i] = (
                    filtered[i] * tri_lftr_k1
                    + filtered[i - 1] * (1.0 - tri_lftr_k1)
                )

            p29 = filtered[29]
            p30 = filtered[30]
            p31 = filtered[31]

            trigger_mode = None

            # Factory path 1: max-hold fast trigger.
            if (
                    p31 > tri_max_hold
                    and p30 > tri_max_hold / 2.0
                    and p29 > tri_max_hold / 3.0):
                trigger_mode = "max_hold"

            # Factory path 2:
            # rising last 3 + last 3 above all earlier points + min hold.
            if trigger_mode is None:
                if p31 > p30 and p30 > p29:
                    dominates = True

                    for j in range(0, 29):
                        if not (
                                p31 > filtered[j]
                                and p30 > filtered[j]
                                and p29 > filtered[j]):
                            dominates = False
                            break

                    if dominates and p31 >= tri_min_hold:
                        trigger_mode = "rising_min_hold"

            if trigger_mode is None:
                continue

            event_time = times[-1]

            # Same synchronized Z/time mapping already used by our
            # native waveform diagnostics.
            event_z = (
                trigger_z
                + probe_speed * (trigger_time - event_time)
            )

            before_trigger_ms = (
                trigger_time - event_time
            ) * 1000.0

            return (
                event_z,
                trigger_mode,
                p29,
                p30,
                p31,
                sample_dt * 1000.0,
                before_trigger_ms,
                end_index,
            )

        return None

    def _analyze_contact_quality(self, samples, trigger_time):
        # Diagnostic only.
        #
        # Use relative waveform properties rather than an absolute
        # force threshold so this can eventually generalize across
        # different V3 SE strain gauges / HX711 scaling.

        pre_trigger = []

        for sample in samples:
            sample_time = sample[0]
            force = float(sample[1])

            if sample_time <= trigger_time:
                pre_trigger.append((sample_time, force))

        pre_trigger.sort(key=lambda item: item[0])

        if len(pre_trigger) < 12:
            return None

        window = pre_trigger[-32:]

        times = [item[0] for item in window]
        data = [item[1] for item in window]

        # Same polarity normalization used by the Creality-style
        # diagnostic so "contact" always rises positively.
        if data[-1] < data[0]:
            data = [-value for value in data]

        # Estimate quiet baseline from the beginning of the history.
        baseline_count = min(12, max(8, len(data) // 3))
        baseline_values = sorted(data[:baseline_count])

        nbase = len(baseline_values)

        if nbase % 2:
            baseline = baseline_values[nbase // 2]
        else:
            baseline = (
                baseline_values[nbase // 2 - 1]
                + baseline_values[nbase // 2]
            ) / 2.0

        deviations = sorted(
            abs(value - baseline)
            for value in data[:baseline_count]
        )

        ndev = len(deviations)

        if ndev % 2:
            mad = deviations[ndev // 2]
        else:
            mad = (
                deviations[ndev // 2 - 1]
                + deviations[ndev // 2]
            ) / 2.0

        # Robust sigma estimate from MAD.
        noise_sigma = mad * 1.4826

        peak_signal = max(data) - baseline
        end_signal = data[-1] - baseline

        if noise_sigma > 1.0e-9:
            snr = end_signal / noise_sigma
        else:
            snr = None

        last3_rising = (
            len(data) >= 3
            and data[-1] > data[-2] > data[-3]
        )

        dominates_history = False

        if len(data) > 3:
            earlier_max = max(data[:-3])
            dominates_history = (
                data[-1] > earlier_max
                and data[-2] > earlier_max
                and data[-3] > earlier_max
            )

        # Find when the rising waveform first exceeds baseline + 3 sigma.
        # This is diagnostic only, not a trigger rule.
        rise_index = None

        if noise_sigma > 1.0e-9:
            rise_level = baseline + 3.0 * noise_sigma

            for i, value in enumerate(data):
                if value >= rise_level:
                    rise_index = i
                    break

        if rise_index is None:
            rise_samples = 0
            rise_ms = None
        else:
            rise_samples = len(data) - rise_index

            if rise_index < len(times):
                rise_ms = (
                    trigger_time - times[rise_index]
                ) * 1000.0
            else:
                rise_ms = None

        return (
            len(data),
            baseline,
            noise_sigma,
            peak_signal,
            end_signal,
            snr,
            last3_rising,
            dominates_history,
            rise_samples,
            rise_ms,
        )

    def cmd_STRAIN_GAUGE_NOZZLE_PREP(self, gcmd):
        return self._run_nozzle_prep(gcmd)

    def _run_nozzle_prep(self, gcmd):
        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()
        reactor = self.printer.get_reactor()

        # Creality factory nozzle-clear geometry:
        #   configured cleaning region X=0..3, Y=5..55
        #   choose a random probe start X=0..3, Y=5..25
        #   probe the second endpoint 30mm farther in Y
        #   perform the actual wipe 5mm inside each measured endpoint
        #
        # Explicit X/Y/LENGTH parameters remain available for diagnostics.
        start_x = gcmd.get_float(
            "X", random.uniform(0.0, 3.0))
        start_y = gcmd.get_float(
            "Y", random.uniform(5.0, 25.0))
        wipe_length = gcmd.get_float(
            "LENGTH", 30.0, above=10.0)

        end_y = start_y + wipe_length

        wipe_inset = 5.0
        wipe_start_y = start_y + wipe_inset
        wipe_end_y = end_y - wipe_inset

        probe_speed = gcmd.get_float("SPEED", 1.00, above=0.0)
        search_end_z = gcmd.get_float(
            "SEARCH_END_Z", 0.0, minval=-0.5, maxval=0.3)
        wipe_speed = gcmd.get_float("WIPE_SPEED", 2.0, above=0.0)
        wipe_depth = gcmd.get_float(
            "WIPE_DEPTH", 0.15, minval=0.0, maxval=0.30)
        clear_probe_count = gcmd.get_int(
            "CLEAR_PROBE_COUNT", 3, minval=1, maxval=9)

        trigger_force = (
            self._native_config_helper.get_trigger_force_grams(gcmd))

        # Creality clears mesh compensation while measuring the physical
        # cleaning surface. Preserve the currently loaded saved profile
        # and restore it before the final G28 Z.
        bed_mesh = self.printer.lookup_object('bed_mesh', None)
        mesh_was_active = False
        active_profile = ""

        if bed_mesh is not None:
            mesh_status = bed_mesh.get_status(reactor.monotonic())
            active_profile = mesh_status.get('profile_name', '')
            mesh_matrix = mesh_status.get('mesh_matrix', [[]])
            mesh_was_active = bool(mesh_matrix and mesh_matrix[0])

            if mesh_was_active and not active_profile:
                raise gcmd.error(
                    "Active bed mesh has no saved profile name. "
                    "Load a saved mesh profile before nozzle prep.")

        if mesh_was_active:
            gcmd.respond_info(
                "Temporarily clearing bed mesh profile '%s' for nozzle prep..."
                % active_profile)
            self.gcode.run_script_from_command("BED_MESH_CLEAR")

        def probe_contact(x, y):
            toolhead.manual_move([None, None, 10.0], 10.0)
            toolhead.wait_moves()

            toolhead.manual_move([x, y, None], self.travel_speed)
            toolhead.wait_moves()

            toolhead.manual_move([None, None, 3.0], 5.0)
            toolhead.wait_moves()

            pos = toolhead.get_position()
            pos[2] = search_end_z

            epos, collector = self._native_primitives.probing_move(
                self._native_tapping_move,
                pos,
                probe_speed,
                gcmd)

            toolhead.flush_step_generation()
            move_end = toolhead.get_last_move_time()
            collected = collector.collect_until(move_end)
            samples = load_cell_probe.check_sensor_errors(
                collected, self.printer)

            trigger_z = epos[2]
            eventtime = reactor.monotonic()
            trigger_time = self._native_primitives.get_status(
                eventtime)["last_trigger_time"]

            trigger_source = (
                self._native_mcu_probe.get_last_trigger_source())

            if trigger_source != 1:
                raise gcmd.error(
                    "Wipe-point X%.1f Y%.1f did not trigger from PRTouch "
                    "(source=%d)"
                    % (x, y, trigger_source))

            threshold_z, onset_z, fit_count = (
                self._analyze_native_contact_samples(
                    samples,
                    trigger_time,
                    trigger_z,
                    probe_speed,
                    trigger_force))

            # Production wipe geometry must use the exact frozen 32-sample
            # MCU PRTouch FIFO that caused the motion trigger.  The general
            # host collector remains diagnostic only.
            creality_samples = (
                self._native_mcu_probe.get_last_prtouch_snapshot())

            if len(creality_samples) != 32:
                raise gcmd.error(
                    "Frozen MCU PRTouch FIFO unavailable/incomplete at "
                    "wipe point X%.1f Y%.1f (samples=%d, expected=32)"
                    % (x, y, len(creality_samples)))

            (
                creality_z,
                creality_count,
                creality_index,
                creality_before_ms,
            ) = self._analyze_creality_contact_event(
                creality_samples,
                trigger_time,
                trigger_z,
                probe_speed)

            quality = self._analyze_contact_quality(
                samples,
                trigger_time)

            factory_replay = self._replay_creality_mcu_trigger(
                samples,
                trigger_time,
                trigger_z,
                probe_speed)

            toolhead.manual_move([None, None, 5.0], 5.0)
            toolhead.wait_moves()

            if threshold_z is None:
                threshold_text = "unavailable"
            else:
                threshold_text = "%.5f" % threshold_z

            if onset_z is None:
                onset_text = "unavailable"
            else:
                onset_text = "%.5f" % onset_z

            gcmd.respond_info(
                "Wipe-point contact X%.1f Y%.1f: "
                "MCU trigger=%.5f raw %.1fg=%s onset=%s fit=%d"
                % (
                    x, y,
                    trigger_z,
                    trigger_force,
                    threshold_text,
                    onset_text,
                    fit_count))

            if creality_z is None:
                raise gcmd.error(
                    "Could not determine Creality waveform event "
                    "at wipe point X%.1f Y%.1f" % (x, y))
            else:
                gcmd.respond_info(
                    "Creality-event X%.1f Y%.1f: "
                    "z=%.5f index=%d before_trigger=%.1fms n=%d"
                    % (
                        x, y,
                        creality_z,
                        creality_index,
                        creality_before_ms,
                        creality_count))

            if factory_replay is None:
                gcmd.respond_info(
                    "Creality-MCU-replay X%.1f Y%.1f: "
                    "NO FACTORY TRIGGER before Kalico halt"
                    % (x, y))
            else:
                (
                    factory_z,
                    factory_mode,
                    factory_p29,
                    factory_p30,
                    factory_p31,
                    factory_dt_ms,
                    factory_before_ms,
                    factory_index,
                ) = factory_replay

                gcmd.respond_info(
                    "Creality-MCU-replay X%.1f Y%.1f: "
                    "z=%.5f mode=%s "
                    "p29=%.1f p30=%.1f p31=%.1f "
                    "dt=%.2fms before_75g=%.1fms index=%d"
                    % (
                        x,
                        y,
                        factory_z,
                        factory_mode,
                        factory_p29,
                        factory_p30,
                        factory_p31,
                        factory_dt_ms,
                        factory_before_ms,
                        factory_index,
                    ))

            if quality is None:
                gcmd.respond_info(
                    "Contact-quality X%.1f Y%.1f: unavailable"
                    % (x, y))
            else:
                (
                    quality_n,
                    baseline,
                    noise_sigma,
                    peak_signal,
                    end_signal,
                    snr,
                    last3_rising,
                    dominates_history,
                    rise_samples,
                    rise_ms,
                ) = quality

                if snr is None:
                    snr_text = "inf/undefined"
                else:
                    snr_text = "%.1f" % snr

                if rise_ms is None:
                    rise_text = "unavailable"
                else:
                    rise_text = "%.1fms" % rise_ms

                gcmd.respond_info(
                    "Contact-quality X%.1f Y%.1f: "
                    "n=%d baseline=%.2fg noise=%.2fg "
                    "peak=%.2fg end=%.2fg SNR=%s "
                    "rising3=%s dominates=%s "
                    "rise_samples=%d rise_time=%s"
                    % (
                        x, y,
                        quality_n,
                        baseline,
                        noise_sigma,
                        peak_signal,
                        end_signal,
                        snr_text,
                        "yes" if last3_rising else "no",
                        "yes" if dominates_history else "no",
                        rise_samples,
                        rise_text))

            return creality_z

        gcmd.respond_info(
            "=== STRAIN GAUGE NOZZLE PREP ===\n"
            "Bed 60C, nozzle 180C probe, 200C wipe, 140C finish\n"
            "Probe line X%.2f Y%.2f -> X%.2f Y%.2f\n"
            "Wipe line  X%.2f Y%.2f -> X%.2f Y%.2f"
            % (
                start_x, start_y,
                start_x, end_y,
                start_x, wipe_start_y,
                start_x, wipe_end_y))

        # Creality-style controlled thermal starting state.
        self.gcode.run_script_from_command("M106 S0")
        self.gcode.run_script_from_command("M140 S60")
        self.gcode.run_script_from_command("M104 S180")
        self.gcode.run_script_from_command("M190 S60")
        self.gcode.run_script_from_command("M109 S180")

        # Match Creality's repeated cleaning-surface probing.
        # Default: three native contacts at each endpoint, then median.
        def probe_contact_median(x, y):
            contacts = []

            for attempt in range(clear_probe_count):
                contact_z = probe_contact(x, y)
                contacts.append(contact_z)

                gcmd.respond_info(
                    "Wipe-point X%.1f Y%.1f pass %d/%d: %.5f"
                    % (
                        x, y,
                        attempt + 1,
                        clear_probe_count,
                        contact_z))

            ordered = sorted(contacts)
            count = len(ordered)

            if count % 2:
                median_z = ordered[count // 2]
            else:
                median_z = (
                    ordered[count // 2 - 1] +
                    ordered[count // 2]
                ) * 0.5

            spread = ordered[-1] - ordered[0]

            gcmd.respond_info(
                "Wipe-point X%.1f Y%.1f median=%.5f spread=%.5f "
                "from %d contacts"
                % (
                    x, y,
                    median_z,
                    spread,
                    count))

            return median_z

        # Creality's nozzle-clear endpoint probes are part of the
        # z_compensate process and use its 1400/2000 PRTouch thresholds.
        prep_prtouch_min_hold = gcmd.get_int(
            "PRTOUCH_MIN_HOLD", self.prtouch_cal_min_hold, minval=1)
        prep_prtouch_max_hold = gcmd.get_int(
            "PRTOUCH_MAX_HOLD", self.prtouch_cal_max_hold, minval=1)

        if prep_prtouch_min_hold >= prep_prtouch_max_hold:
            raise gcmd.error(
                "PRTOUCH_MIN_HOLD must be less than PRTouch max hold")

        normal_prtouch_min_hold, normal_prtouch_max_hold = (
            self._native_mcu_probe.get_prtouch_thresholds()
        )
        prtouch_thresholds_switched = False

        try:
            if not self._native_mcu_probe.set_prtouch_thresholds(
                    prep_prtouch_min_hold,
                    prep_prtouch_max_hold):
                raise gcmd.error(
                    "PRTouch waveform triggering is not enabled")

            prtouch_thresholds_switched = True

            gcmd.respond_info(
                "Nozzle-prep PRTouch thresholds: min=%d max=%d"
                % (
                    prep_prtouch_min_hold,
                    prep_prtouch_max_hold,
                )
            )

            start_contact = probe_contact_median(start_x, start_y)
            end_contact = probe_contact_median(start_x, end_y)

        finally:
            if prtouch_thresholds_switched:
                try:
                    self._native_mcu_probe.set_prtouch_thresholds(
                        normal_prtouch_min_hold,
                        normal_prtouch_max_hold)
                    gcmd.respond_info(
                        "Restored normal PRTouch thresholds: min=%d max=%d"
                        % (
                            normal_prtouch_min_hold,
                            normal_prtouch_max_hold,
                        )
                    )
                except Exception as e:
                    gcmd.respond_info(
                        "WARNING: Could not restore normal PRTouch "
                        "thresholds: %s" % str(e))

        # Heat to Creality's nozzle rubbing temperature.
        self.gcode.run_script_from_command("M109 S200")

        # Creality factory wipe geometry around the measured
        # waveform-event surface.
        start_wipe_z = start_contact + wipe_depth
        end_wipe_z = end_contact - wipe_depth

        gcmd.respond_info(
            "Factory wipe Z %.5f -> %.5f, depth=%.3fmm, speed=%.2fmm/s"
            % (
                start_wipe_z,
                end_wipe_z,
                wipe_depth,
                wipe_speed))

        toolhead.manual_move([None, None, 5.0], 5.0)
        toolhead.wait_moves()

        toolhead.manual_move(
            [start_x, wipe_start_y, None],
            self.travel_speed)
        toolhead.wait_moves()

        toolhead.manual_move(
            [None, None, start_wipe_z],
            2.0)
        toolhead.wait_moves()

        # Creality factory order: retract filament immediately before
        # rubbing the hot nozzle across the measured cleaning surface.
        pumpback_mm = gcmd.get_float(
            "PUMPBACK", 10.0, minval=0.0, maxval=20.0)

        if pumpback_mm > 0.0:
            gcmd.respond_info(
                "Filament pumpback: retracting %.1fmm before wipe..."
                % pumpback_mm)

            gcode_move = self.printer.lookup_object('gcode_move')
            was_absolute_extrude = gcode_move.get_status(
                reactor.monotonic()
            ).get('absolute_extrude', True)

            self.gcode.run_script_from_command("M83")
            self.gcode.run_script_from_command(
                "G1 E-%.3f F300" % pumpback_mm)

            if was_absolute_extrude:
                self.gcode.run_script_from_command("M82")
            else:
                self.gcode.run_script_from_command("M83")

        # Factory behavior: one controlled sloped traverse, beginning
        # 5mm inside the first measured endpoint and ending 5mm before
        # the second measured endpoint.  This leaves the measurement
        # locations themselves outside the rubbing stroke.
        toolhead.manual_move(
            [start_x, wipe_end_y, end_wipe_z],
            wipe_speed)
        toolhead.wait_moves()

        toolhead.manual_move([None, None, 10.0], 5.0)
        toolhead.wait_moves()

        # Cool to Creality's calibration temperature.
        self.gcode.run_script_from_command("M104 S140")
        self.gcode.run_script_from_command("M106 S255")
        self.gcode.run_script_from_command("M109 S140")
        self.gcode.run_script_from_command("M106 S0")

        if mesh_was_active and active_profile:
            gcmd.respond_info(
                "Restoring bed mesh profile '%s'..."
                % active_profile)
            self.gcode.run_script_from_command(
                'BED_MESH_PROFILE LOAD="%s"' % active_profile)

        gcmd.respond_info(
            "Nozzle prep complete. Re-homing Z at 140C / 60C...")
        self.gcode.run_script_from_command("G28 Z")

        gcmd.respond_info(
            "=== NOZZLE PREP COMPLETE ===\n"
            "Bed target: 60C\n"
            "Nozzle target: 140C\n"
            "No Z offset or configuration was changed.")

    def cmd_STRAIN_GAUGE_PRT_THRESHOLD_BENCHMARK(self, gcmd):
        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()
        reactor = self.printer.get_reactor()

        speed = gcmd.get_float("SPEED", 1.00, above=0.0)
        end_z = gcmd.get_float(
            "END_Z", 0.10, minval=-0.5, maxval=0.3)

        start_z = 3.0
        retract_z = 5.0

        trigger_force = (
            self._native_config_helper.get_trigger_force_grams(gcmd))

        normal_min, normal_max = (
            self._native_mcu_probe.get_prtouch_thresholds()
        )

        sequence = [
            ("NORMAL",
             self.prtouch_min_hold,
             self.prtouch_max_hold),
            ("ZCOMP",
             self.prtouch_cal_min_hold,
             self.prtouch_cal_max_hold),
            ("NORMAL",
             self.prtouch_min_hold,
             self.prtouch_max_hold),
            ("ZCOMP",
             self.prtouch_cal_min_hold,
             self.prtouch_cal_max_hold),
            ("NORMAL",
             self.prtouch_min_hold,
             self.prtouch_max_hold),
            ("ZCOMP",
             self.prtouch_cal_min_hold,
             self.prtouch_cal_max_hold),
        ]

        results = []

        gcmd.respond_info(
            "=== PRTOUCH THRESHOLD A/B BENCHMARK ===\n"
            "Physical point: X=%.2f Y=%.2f\n"
            "Speed: %.2f mm/s  END_Z=%.3f\n"
            "Sequence: 1000/1500 -> 1400/2000 repeated 3 times"
            % (
                self.pad_x,
                self.pad_y,
                speed,
                end_z,
            )
        )

        # Move to the exact same physical nozzle point for all six contacts.
        toolhead.manual_move([None, None, retract_z], 5.0)
        toolhead.wait_moves()
        toolhead.manual_move(
            [self.pad_x, self.pad_y, None],
            self.travel_speed)
        toolhead.wait_moves()

        try:
            for run_index, (label, min_hold, max_hold) in enumerate(
                    sequence, start=1):

                if not self._native_mcu_probe.set_prtouch_thresholds(
                        min_hold, max_hold):
                    raise gcmd.error(
                        "PRTouch waveform triggering is not enabled")

                # Allow the runtime MCU command to be processed before probing.
                reactor.pause(reactor.monotonic() + 0.05)

                toolhead.manual_move(
                    [None, None, start_z], 5.0)
                toolhead.wait_moves()

                pos = toolhead.get_position()
                pos[2] = end_z

                epos, collector = (
                    self._native_primitives.probing_move(
                        self._native_tapping_move,
                        pos,
                        speed,
                        gcmd))

                toolhead.flush_step_generation()
                move_end = toolhead.get_last_move_time()

                collected = collector.collect_until(move_end)
                samples = load_cell_probe.check_sensor_errors(
                    collected, self.printer)

                trigger_z = epos[2]

                eventtime = reactor.monotonic()
                trigger_time = (
                    self._native_primitives.get_status(
                        eventtime)["last_trigger_time"])

                trigger_source = (
                    self._native_mcu_probe.get_last_trigger_source())

                threshold_z, onset_z, fit_count = (
                    self._analyze_native_contact_samples(
                        samples,
                        trigger_time,
                        trigger_z,
                        speed,
                        trigger_force))

                results.append({
                    "run": run_index,
                    "label": label,
                    "min_hold": min_hold,
                    "max_hold": max_hold,
                    "trigger": trigger_z,
                    "source": trigger_source,
                    "threshold": threshold_z,
                })

                source_name = {
                    1: "prtouch",
                    2: "force",
                }.get(trigger_source, "unknown")

                gcmd.respond_info(
                    "Run %d/6 %-6s %d/%d: "
                    "MCU trigger=%.5f source=%d(%s) "
                    "raw %.1fg=%s"
                    % (
                        run_index,
                        label,
                        min_hold,
                        max_hold,
                        trigger_z,
                        trigger_source,
                        source_name,
                        trigger_force,
                        ("%.5f" % threshold_z)
                        if threshold_z is not None else "N/A",
                    )
                )

                toolhead.manual_move(
                    [None, None, retract_z], 5.0)
                toolhead.wait_moves()

                reactor.pause(
                    reactor.monotonic() + 0.50)

        finally:
            try:
                self._native_mcu_probe.set_prtouch_thresholds(
                    normal_min, normal_max)

                gcmd.respond_info(
                    "Restored normal PRTouch thresholds: min=%d max=%d"
                    % (normal_min, normal_max)
                )
            except Exception as e:
                gcmd.respond_info(
                    "WARNING: Could not restore normal PRTouch "
                    "thresholds: %s" % str(e))

            if not self.printer.is_shutdown():
                try:
                    toolhead.manual_move(
                        [None, None, retract_z], 5.0)
                    toolhead.wait_moves()
                except Exception:
                    pass

        lines = ["=== PRTOUCH THRESHOLD A/B SUMMARY ==="]

        for label in ["NORMAL", "ZCOMP"]:
            rows = [
                row for row in results
                if row["label"] == label
            ]

            triggers = [
                row["trigger"] for row in rows
                if row["source"] == 1
            ]

            if triggers:
                ordered = sorted(triggers)
                median = ordered[len(ordered) // 2]

                lines.append(
                    "%-6s MCU trigger: median=%.5f "
                    "min=%.5f max=%.5f spread=%.5f"
                    % (
                        label,
                        median,
                        min(triggers),
                        max(triggers),
                        max(triggers) - min(triggers),
                    )
                )
            else:
                lines.append(
                    "%-6s MCU trigger: no PRTouch-source contacts"
                    % label
                )

        # Pair each NORMAL run with the immediately following ZCOMP run.
        for pair_index in range(3):
            normal_row = results[pair_index * 2]
            zcomp_row = results[pair_index * 2 + 1]

            lines.append(
                "Pair %d ZCOMP-NORMAL trigger delta: %+.5f mm"
                % (
                    pair_index + 1,
                    zcomp_row["trigger"] - normal_row["trigger"],
                )
            )

        self.gcode.respond_info("\n".join(lines))

    def cmd_STRAIN_GAUGE_NATIVE_BENCHMARK(self, gcmd):
        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()
        reactor = self.printer.get_reactor()
        trigger_force = (
            self._native_config_helper.get_trigger_force_grams(gcmd))

        start_z = 3.0
        end_z = gcmd.get_float(
            "END_Z", 0.5, minval=-0.5, maxval=0.5)
        retract_z = 5.0

        speed_cycles = [
            [0.25, 0.50, 1.00],
            [1.00, 0.50, 0.25],
            [0.25, 0.50, 1.00],
        ]

        results = []
        references = []

        probe = self.printer.lookup_object('probe')
        probe_offsets = probe.get_offsets()
        probe_x = self.pad_x - probe_offsets[0]
        probe_y = self.pad_y - probe_offsets[1]

        def read_temperatures():
            eventtime = reactor.monotonic()
            extruder_status = self.printer.lookup_object(
                'extruder').get_status(eventtime)
            bed_status = self.printer.lookup_object(
                'heater_bed').get_status(eventtime)

            return {
                "nozzle": extruder_status.get("temperature", 0.0),
                "nozzle_target": extruder_status.get("target", 0.0),
                "bed": bed_status.get("temperature", 0.0),
                "bed_target": bed_status.get("target", 0.0),
            }

        def take_cr_reference(label):
            # Measure the exact same physical bed point with CR Touch.
            toolhead.manual_move([None, None, 10.0], 10.0)
            toolhead.wait_moves()

            toolhead.manual_move(
                [probe_x, probe_y, None],
                self.travel_speed)
            toolhead.wait_moves()

            probe_pos = probe.run_probe(gcmd)

            if probe_pos is None or len(probe_pos) < 3:
                raise gcmd.error(
                    "CR Touch did not return a valid benchmark reference")

            temps = read_temperatures()

            reference = {
                "label": label,
                "z": probe_pos[2],
                "nozzle": temps["nozzle"],
                "nozzle_target": temps["nozzle_target"],
                "bed": temps["bed"],
                "bed_target": temps["bed_target"],
            }

            gcmd.respond_info(
                "CR %s: Z=%.5f  nozzle=%.1f/%.1fC  bed=%.1f/%.1fC"
                % (
                    label,
                    reference["z"],
                    reference["nozzle"],
                    reference["nozzle_target"],
                    reference["bed"],
                    reference["bed_target"]))

            # Return safely to nozzle-over-strain-pad position.
            toolhead.manual_move([None, None, 10.0], 10.0)
            toolhead.wait_moves()
            toolhead.manual_move(
                [self.pad_x, self.pad_y, None],
                self.travel_speed)
            toolhead.wait_moves()

            return reference

        gcmd.respond_info(
            "=== NATIVE STRAIN BENCHMARK ===\n"
            "9 contacts, fresh tare each pass\n"
            "Speeds: 0.25 / 0.50 / 1.00 mm/s\n"
            "Trigger force: %.1fg"
            % trigger_force)

        # Establish CR Touch reference before any strain contacts.
        references.append(take_cr_reference("START"))

        run_number = 0

        try:
            for cycle_index, speeds in enumerate(speed_cycles):
                for speed in speeds:
                    run_number += 1

                    toolhead.manual_move(
                        [None, None, start_z], 5.0)
                    toolhead.wait_moves()

                    pos = toolhead.get_position()
                    pos[2] = end_z

                    epos, collector = (
                        self._native_primitives.probing_move(
                            self._native_tapping_move,
                            pos,
                            speed,
                            gcmd))

                    toolhead.flush_step_generation()
                    move_end = toolhead.get_last_move_time()
                    collected = collector.collect_until(move_end)
                    samples = load_cell_probe.check_sensor_errors(
                        collected, self.printer)

                    trigger_z = epos[2]
                    eventtime = reactor.monotonic()
                    trigger_time = (
                        self._native_primitives.get_status(
                            eventtime)["last_trigger_time"])

                    threshold_z, onset_z, fit_count = (
                        self._analyze_native_contact_samples(
                            samples,
                            trigger_time,
                            trigger_z,
                            speed,
                            trigger_force))

                    temps = read_temperatures()

                    results.append({
                        "run": run_number,
                        "cycle": cycle_index + 1,
                        "speed": speed,
                        "trigger": trigger_z,
                        "threshold": threshold_z,
                        "onset": onset_z,
                        "fit_count": fit_count,
                        "nozzle": temps["nozzle"],
                        "nozzle_target": temps["nozzle_target"],
                        "bed": temps["bed"],
                        "bed_target": temps["bed_target"],
                    })

                    gcmd.respond_info(
                        "Run %d/9 C%d %.2fmm/s: "
                        "trigger=%.5f threshold=%s onset=%s fit=%d "
                        "Tn=%.1f/%.1fC Tb=%.1f/%.1fC"
                        % (
                            run_number,
                            cycle_index + 1,
                            speed,
                            trigger_z,
                            "%.5f" % threshold_z
                            if threshold_z is not None else "N/A",
                            "%.5f" % onset_z
                            if onset_z is not None else "N/A",
                            fit_count,
                            temps["nozzle"],
                            temps["nozzle_target"],
                            temps["bed"],
                            temps["bed_target"]))

                    toolhead.manual_move(
                        [None, None, retract_z], 5.0)
                    toolhead.wait_moves()

                    reactor.pause(
                        reactor.monotonic() + 0.50)

                # CR Touch reference after every complete speed cycle.
                references.append(
                    take_cr_reference(
                        "CYCLE%d" % (cycle_index + 1)))

        except self.printer.command_error:
            if not self.printer.is_shutdown():
                toolhead.manual_move(
                    [None, None, retract_z], 5.0)
                toolhead.wait_moves()
            raise

        lines = ["=== BENCHMARK SUMMARY ==="]

        for speed in [0.25, 0.50, 1.00]:
            rows = [
                row for row in results
                if abs(row["speed"] - speed) < 0.0001
            ]

            lines.append("%.2f mm/s:" % speed)

            for field, label in [
                    ("trigger", "MCU trigger"),
                    ("threshold", "20g cross"),
                    ("onset", "Contact onset")]:

                values = [
                    row[field] for row in rows
                    if row[field] is not None
                ]

                if not values:
                    lines.append(
                        "  %-13s N/A" % label)
                    continue

                avg = sum(values) / float(len(values))
                minimum = min(values)
                maximum = max(values)
                spread = maximum - minimum

                lines.append(
                    "  %-13s avg=%.5f min=%.5f "
                    "max=%.5f spread=%.5f"
                    % (
                        label,
                        avg,
                        minimum,
                        maximum,
                        spread))

        all_onsets = [
            row["onset"] for row in results
            if row["onset"] is not None
        ]

        if all_onsets:
            lines.append(
                "All onset values: avg=%.5f spread=%.5f"
                % (
                    sum(all_onsets) / float(len(all_onsets)),
                    max(all_onsets) - min(all_onsets)))

        lines.append("CR Touch references:")

        for ref in references:
            lines.append(
                "  %-6s Z=%.5f  nozzle=%.1fC  bed=%.1fC"
                % (
                    ref["label"],
                    ref["z"],
                    ref["nozzle"],
                    ref["bed"]))

        cr_values = [ref["z"] for ref in references]
        if cr_values:
            lines.append(
                "CR Touch drift: min=%.5f max=%.5f spread=%.5f"
                % (
                    min(cr_values),
                    max(cr_values),
                    max(cr_values) - min(cr_values)))

        nozzle_values = [row["nozzle"] for row in results]
        bed_values = [row["bed"] for row in results]

        if nozzle_values:
            lines.append(
                "Nozzle temp range during strain runs: "
                "%.1fC to %.1fC"
                % (min(nozzle_values), max(nozzle_values)))

        if bed_values:
            lines.append(
                "Bed temp range during strain runs: "
                "%.1fC to %.1fC"
                % (min(bed_values), max(bed_values)))

        gcmd.respond_info("\n".join(lines))

    def cmd_STRAIN_GAUGE_NATIVE_CONTACT_TEST(self, gcmd):
        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()

        start_z = 3.0
        end_z = gcmd.get_float("END_Z", 0.5, minval=-0.5, maxval=0.5)
        speed = gcmd.get_float("SPEED", 0.25, above=0.0)
        retract_z = 5.0
        test_x = gcmd.get_float("X", self.pad_x)
        test_y = gcmd.get_float("Y", self.pad_y)

        gcmd.respond_info(
            "Native contact test: X=%.1f Y=%.1f, "
            "start Z=%.2f, limit Z=%.2f, speed=%.2f mm/s"
            % (test_x, test_y, start_z, end_z, speed))

        # Travel safely above the pad first.
        toolhead.manual_move([None, None, 10.0], 10.0)
        toolhead.wait_moves()
        toolhead.manual_move(
            [test_x, test_y, None], self.travel_speed)
        toolhead.wait_moves()
        toolhead.manual_move([None, None, start_z], 5.0)
        toolhead.wait_moves()

        pos = toolhead.get_position()
        pos[2] = end_z

        try:
            epos, collector = self._native_primitives.probing_move(
                self._native_tapping_move, pos, speed, gcmd)

            toolhead.flush_step_generation()
            move_end = toolhead.get_last_move_time()
            results = collector.collect_until(move_end)
            samples = load_cell_probe.check_sensor_errors(
                results, self.printer)

        except self.printer.command_error:
            if not self.printer.is_shutdown():
                toolhead.manual_move([None, None, retract_z], 5.0)
                toolhead.wait_moves()
            raise

        trigger_z = epos[2]
        eventtime = self.printer.get_reactor().monotonic()
        trigger_time = self._native_primitives.get_status(
            eventtime)["last_trigger_time"]

        creality_samples = (
            self._native_mcu_probe.get_last_prtouch_snapshot()
        )

        if len(creality_samples) == 32:
            (
                creality_event_z,
                creality_event_count,
                creality_event_index,
                creality_before_ms,
            ) = self._analyze_creality_contact_event(
                creality_samples,
                trigger_time,
                trigger_z,
                speed)

            if creality_event_z is not None:
                gcmd.respond_info(
                    "Frozen MCU event diagnostic: Z=%.5f "
                    "index=%d before_trigger=%.1fms samples=%d"
                    % (
                        creality_event_z,
                        creality_event_index,
                        creality_before_ms,
                        creality_event_count,
                    ))
            else:
                gcmd.respond_info(
                    "Frozen MCU event diagnostic unavailable "
                    "(samples=%d)"
                    % creality_event_count)
        else:
            gcmd.respond_info(
                "Frozen MCU PRTouch FIFO unavailable/incomplete "
                "(samples=%d expected=32)"
                % len(creality_samples))

        # Map timestamped HX711 samples back onto the constant-speed
        # Z trajectory around the MCU trigger.
        trigger_force = (
            self._native_config_helper.get_trigger_force_grams(gcmd))
        trace = []
        mapped = []

        for sample in samples:
            sample_time = sample[0]
            force = sample[1]

            delta_t = trigger_time - sample_time
            sample_z = trigger_z + speed * delta_t

            if abs(delta_t) <= 0.150:
                mapped.append((sample_time, sample_z, force))
                trace.append(
                    "  dt=%+8.4f s  Z=%8.5f  force=%8.2f g"
                    % (-delta_t, sample_z, force))

        # Interpolate the raw force-threshold crossing.
        threshold_z = None
        for i in range(1, len(mapped)):
            _, prev_z, prev_force = mapped[i - 1]
            _, cur_z, cur_force = mapped[i]
            prev_mag = abs(prev_force)
            cur_mag = abs(cur_force)

            if (prev_mag < trigger_force <= cur_mag
                    and cur_mag > prev_mag):
                fraction = (
                    (trigger_force - prev_mag) /
                    (cur_mag - prev_mag)
                )
                threshold_z = (
                    prev_z + fraction * (cur_z - prev_z)
                )
                break

        # Estimate physical contact onset by fitting Z versus force
        # magnitude through the rising contact ramp, then extrapolating
        # that line back to zero force.  This is diagnostic only.
        fit_min_force = max(3.0, trigger_force * 0.15)
        fit_max_force = trigger_force * 1.50
        fit_points = []

        for sample_time, sample_z, force in mapped:
            # Fit only the rising force ramp BEFORE the MCU trigger.
            # Post-trigger samples include the compressed/settled plateau
            # and will bias the extrapolated contact onset.
            if sample_time > trigger_time:
                continue

            mag = abs(force)
            if fit_min_force <= mag <= fit_max_force:
                fit_points.append((mag, sample_z))

        contact_onset_z = None
        if len(fit_points) >= 2:
            n = float(len(fit_points))
            sx = sum(point[0] for point in fit_points)
            sy = sum(point[1] for point in fit_points)
            sxx = sum(point[0] * point[0] for point in fit_points)
            sxy = sum(point[0] * point[1] for point in fit_points)
            denom = n * sxx - sx * sx

            if abs(denom) > 1.0e-12:
                slope = (n * sxy - sx * sy) / denom
                contact_onset_z = (sy - slope * sx) / n

        toolhead.manual_move([None, None, retract_z], 5.0)
        toolhead.wait_moves()

        gcmd.respond_info(
            "Native nozzle contact SUCCESS at Z=%.5f; "
            "trigger_time=%.6f; retracted to Z=%.1f"
            % (trigger_z, trigger_time, retract_z))

        if threshold_z is not None:
            gcmd.respond_info(
                "Raw %.1fg threshold crossing Z=%.5f"
                % (trigger_force, threshold_z))
        else:
            gcmd.respond_info(
                "Raw %.1fg threshold crossing could not be interpolated"
                % trigger_force)

        if contact_onset_z is not None:
            gcmd.respond_info(
                "Estimated contact onset Z=%.5f "
                "(linear ramp fit, %d samples)"
                % (contact_onset_z, len(fit_points)))
        else:
            gcmd.respond_info(
                "Estimated contact onset unavailable "
                "(only %d ramp samples)"
                % len(fit_points))

        if trace:
            gcmd.respond_info(
                "HX711 waveform around trigger:\n%s"
                % "\n".join(trace))
        else:
            gcmd.respond_info(
                "HX711 waveform: no samples found within +/-150 ms")

    def cmd_STRAIN_GAUGE_NATIVE_STATUS(self, gcmd):
        steppers = self._native_primitives.get_steppers()
        names = [s.get_name() for s in steppers]
        gcmd.respond_info(
            "Native strain trigger steppers: %s"
            % (", ".join(names) if names else "NONE"))

    cmd_STRAIN_GAUGE_NATIVE_AIR_TEST_help = (
        "Test native MCU strain trigger safely above the bed")
    def cmd_STRAIN_GAUGE_NATIVE_AIR_TEST(self, gcmd):
        if not self._check_homed():
            raise gcmd.error("Printer must be homed first! Run G28")

        toolhead = self._get_toolhead()
        reactor = self.printer.get_reactor()
        start_z = 15.0
        end_z = 8.0
        speed = 0.5

        gcmd.respond_info(
            "Native MCU air test: moving to Z=%.1f. "
            "Descent begins in 3 seconds to Z=%.1f at %.1f mm/s. "
            "Press the bed ONLY after Z starts moving."
            % (start_z, end_z, speed))

        toolhead.manual_move([None, None, start_z], 10.0)
        toolhead.wait_moves()

        reactor.pause(reactor.monotonic() + 3.0)

        pos = toolhead.get_position()
        pos[2] = end_z

        try:
            epos, is_good = self._native_tapping_move.probing_move(
                pos, speed, gcmd)
        except self.printer.command_error:
            if not self.printer.is_shutdown():
                toolhead.manual_move([None, None, start_z], 10.0)
                toolhead.wait_moves()
            raise

        trigger_z = epos[2]

        toolhead.manual_move([None, None, start_z], 10.0)
        toolhead.wait_moves()

        gcmd.respond_info(
            "Native MCU trigger SUCCESS at Z=%.5f; retracted to Z=%.1f"
            % (trigger_z, start_z))

    cmd_STRAIN_GAUGE_TARE_help = "Tare the strain gauge sensor"
    def cmd_STRAIN_GAUGE_TARE(self, gcmd):
        self._tare_sensor(gcmd)

    cmd_STRAIN_GAUGE_READ_help = "Read current strain gauge force"
    def cmd_STRAIN_GAUGE_READ(self, gcmd):
        if not self.load_cell.is_calibrated():
            raise gcmd.error("Load cell not calibrated! Set counts_per_gram "
                             "and reference_tare_counts in config.")
        if not self.load_cell.is_tared():
            raise gcmd.error("Load cell not tared! Run STRAIN_GAUGE_TARE")
        force = self._read_force_grams()
        if force is None:
            raise gcmd.error("Could not read force from sensor")
        counts = self.load_cell.avg_counts(5)
        gcmd.respond_info("Force: %.2f g  (raw counts: %d, tare: %d)"
                          % (force, int(counts),
                             self.load_cell.get_tare_counts()))

    def get_status(self, eventtime):
        return self.load_cell.get_status(eventtime)


def load_config(config):
    return StrainGaugeZCal(config)
