// Support homing/probing "trigger" notification from analog sensors
//
// Copyright (C) 2025  Gareth Farrington <gareth@waves.ky>
// Copyright (C) 2024-2026  Kevin O'Connor <kevin@koconnor.net>
//
// This file may be distributed under the terms of the GNU GPLv3 license.

#include "basecmd.h" // oid_alloc
#include "board/io.h" // writeb
#include "board/misc.h" // timer_read_time
#include "command.h" // DECL_COMMAND
#include "sched.h" // shutdown
#include "sos_filter.h" // sos_filter_apply
#include "trigger_analog.h" // trigger_analog_update
#include "trsync.h" // trsync_do_trigger

// Creality V3 SE PRTouch V2 waveform trigger.
// The V3 SE HX711 runs at approximately 80Hz.
#define PRTOUCH_BUF_LEN 32
#define PRTOUCH_Q16_ONE 65536LL
#define PRTOUCH_HP_COEFF_Q16 56639LL
#define PRTOUCH_LP_K1_Q16 45875LL

// Main trigger_analog storage
struct trigger_analog {
    // Raw value range check
    int32_t raw_min, raw_max;
    // Filtering
    struct sos_filter *sf;
    // Trigger value checking
    int32_t trigger_value, trigger_peak;
    uint8_t trigger_type;
    // Trsync triggering
    uint8_t flags, trigger_reason, error_reason;
    struct trsync *ts;
    uint32_t homing_clock;
    // Sensor activity monitoring
    uint8_t monitor_max, monitor_count;
    struct timer time;
    uint32_t monitor_ticks;

    // Optional Creality-compatible PRTouch waveform trigger.
    uint8_t prtouch_enabled;
    uint8_t prtouch_count;
    uint8_t prtouch_index;
    uint32_t prtouch_min_hold;
    uint32_t prtouch_max_hold;
    int32_t prtouch_tare_counts;
    int32_t prtouch_buf[PRTOUCH_BUF_LEN];
};

// Homing flags
enum {
    TA_AWAIT_HOMING = 1<<1, TA_CAN_TRIGGER = 1<<2
};

// Trigger types
enum {
    TT_ABS_GE, TT_GT, TT_DIFF_PEAK_GT
};
DECL_ENUMERATION("trigger_analog_type", "abs_ge", TT_ABS_GE);
DECL_ENUMERATION("trigger_analog_type", "gt", TT_GT);
DECL_ENUMERATION("trigger_analog_type", "diff_peak_gt", TT_DIFF_PEAK_GT);

// Sample errors sent via trsync error code
enum {
    TE_RAW_RANGE, TE_OVERFLOW, TE_MONITOR, TE_SENSOR_SPECIFIC
};
DECL_ENUMERATION("trigger_analog_error:", "RAW_RANGE", TE_RAW_RANGE);
DECL_ENUMERATION("trigger_analog_error:", "OVERFLOW", TE_OVERFLOW);
DECL_ENUMERATION("trigger_analog_error:", "MONITOR", TE_MONITOR);
DECL_ENUMERATION("trigger_analog_error:", "SENSOR_SPECIFIC"
                 , TE_SENSOR_SPECIFIC);

// Timer callback that monitors for sensor timeouts
static uint_fast8_t
monitor_event(struct timer *t)
{
    struct trigger_analog *ta = container_of(t, struct trigger_analog, time);

    if (!(ta->flags & TA_CAN_TRIGGER))
        return SF_DONE;

    if (ta->monitor_count > ta->monitor_max) {
        trsync_do_trigger(ta->ts, ta->error_reason + TE_MONITOR);
        return SF_DONE;
    }

    // A sample was recently delivered, continue monitoring
    ta->monitor_count++;
    ta->time.waketime += ta->monitor_ticks;
    return SF_RESCHEDULE;
}

// Note recent activity
static void
monitor_note_activity(struct trigger_analog *ta)
{
    writeb(&ta->monitor_count, 0);
}


// Return absolute magnitude without overflowing INT32_MIN.
static inline int64_t
prtouch_abs32(int32_t value)
{
    return value < 0 ? -(int64_t)value : (int64_t)value;
}

static void
prtouch_reset(struct trigger_analog *ta)
{
    ta->prtouch_count = 0;
    ta->prtouch_index = 0;
    for (uint8_t i = 0; i < PRTOUCH_BUF_LEN; i++)
        ta->prtouch_buf[i] = 0;
}

static void
prtouch_add_sample(struct trigger_analog *ta, int32_t value)
{
    ta->prtouch_buf[ta->prtouch_index] = value;
    ta->prtouch_index = (ta->prtouch_index + 1) % PRTOUCH_BUF_LEN;

    if (ta->prtouch_count < PRTOUCH_BUF_LEN)
        ta->prtouch_count++;
}

// Creality PRTouch V2 non-ADC trigger semantics.
//
// raw HX711 -> tare subtraction -> rolling 32 samples
// -> polarity normalization
// -> 3-sample minimum-absolute preprocessing
// -> high-pass
// -> recursive low-pass
// -> max-hold OR rising/dominance/min-hold trigger
static uint8_t
prtouch_check_trigger(struct trigger_analog *ta)
{
    if (ta->prtouch_count < PRTOUCH_BUF_LEN)
        return 0;

    // Once full, prtouch_index points at the oldest sample.
    uint8_t base = ta->prtouch_index;

    int32_t first = ta->prtouch_buf[base];
    uint8_t last_idx =
        (base + PRTOUCH_BUF_LEN - 1) % PRTOUCH_BUF_LEN;
    int32_t last = ta->prtouch_buf[last_idx];
    uint8_t invert = last < first;

    int32_t s0 = first;
    int32_t s1 =
        ta->prtouch_buf[(base + 1) % PRTOUCH_BUF_LEN];
    int32_t s2 =
        ta->prtouch_buf[(base + 2) % PRTOUCH_BUF_LEN];

    if (invert) {
        s0 = -s0;
        s1 = -s1;
        s2 = -s2;
    }

    int32_t prev_data = 0;
    int64_t hp_prev = 0;
    int64_t lp_prev = 0;

    // Creality filtered[0] starts at zero.
    int64_t earlier_max = 0;

    int64_t p29 = 0;
    int64_t p30 = 0;
    int64_t p31 = 0;

    for (uint8_t i = 0; i < PRTOUCH_BUF_LEN; i++) {
        int32_t data_i;

        // Creality T filter. The final two samples remain unmodified.
        if (i < PRTOUCH_BUF_LEN - 2) {
            int32_t chosen =
                prtouch_abs32(s0) < prtouch_abs32(s1)
                ? s0 : s1;

            if (prtouch_abs32(s2) < prtouch_abs32(chosen))
                chosen = s2;

            data_i = chosen;
        } else {
            data_i = s0;
        }

        if (i != 0) {
            int64_t input =
                ((int64_t)data_i - (int64_t)prev_data)
                * PRTOUCH_Q16_ONE;
            input += hp_prev;

            int64_t hp =
                (input * PRTOUCH_HP_COEFF_Q16) >> 16;

            int64_t lp =
                (
                    hp * PRTOUCH_LP_K1_Q16
                    + lp_prev
                      * (PRTOUCH_Q16_ONE - PRTOUCH_LP_K1_Q16)
                ) >> 16;

            hp_prev = hp;
            lp_prev = lp;

            if (i <= PRTOUCH_BUF_LEN - 4) {
                if (lp > earlier_max)
                    earlier_max = lp;
            } else if (i == PRTOUCH_BUF_LEN - 3) {
                p29 = lp;
            } else if (i == PRTOUCH_BUF_LEN - 2) {
                p30 = lp;
            } else {
                p31 = lp;
            }
        }

        prev_data = data_i;

        if (i < PRTOUCH_BUF_LEN - 1) {
            s0 = s1;
            s1 = s2;

            uint8_t next_pos = i + 3;
            if (next_pos < PRTOUCH_BUF_LEN) {
                uint8_t idx =
                    (base + next_pos) % PRTOUCH_BUF_LEN;
                s2 = ta->prtouch_buf[idx];

                if (invert)
                    s2 = -s2;
            }
        }
    }

    int64_t min_hold =
        (int64_t)ta->prtouch_min_hold * PRTOUCH_Q16_ONE;
    int64_t max_hold =
        (int64_t)ta->prtouch_max_hold * PRTOUCH_Q16_ONE;

    // Factory path 1: max-hold fast trigger.
    if (p31 > max_hold
        && p30 > max_hold / 2
        && p29 > max_hold / 3)
        return 1;

    // Factory path 2: final three points must be rising.
    if (!(p31 > p30 && p30 > p29))
        return 0;

    // Final three must dominate all earlier filtered points.
    if (!(p31 > earlier_max
          && p30 > earlier_max
          && p29 > earlier_max))
        return 0;

    // Factory minimum hold.
    if (p31 < min_hold)
        return 0;

    return 1;
}

// Check if a value should signal a "trigger" event
static int
check_trigger(struct trigger_analog *ta, uint32_t time, int32_t value)
{
    switch (ta->trigger_type) {
    case TT_ABS_GE: ;
        uint32_t abs_value = value < 0 ? -value : value;
        return abs_value >= ta->trigger_value;
    case TT_GT:
        return value > ta->trigger_value;
    case TT_DIFF_PEAK_GT:
        if (value > ta->trigger_peak) {
            ta->trigger_peak = value;
            return 0;
        }
        uint32_t delta = ta->trigger_peak - value;
        return delta > ta->trigger_value;
    }
    return 0;
}

// Reset fields associated with trigger checking
static void
trigger_reset(struct trigger_analog *ta)
{
    ta->trigger_peak = INT32_MIN;
}

// Stop homing due to an error
static void
cancel_homing(struct trigger_analog *ta, uint8_t error_code)
{
    if (!(ta->flags & TA_CAN_TRIGGER))
        return;
    ta->flags = 0;
    trsync_do_trigger(ta->ts, ta->error_reason + error_code);
}

// Handle an error reported by the sensor
void
trigger_analog_note_error(struct trigger_analog *ta, uint8_t sensor_code)
{
    if (!ta)
        return;
    cancel_homing(ta, sensor_code + TE_SENSOR_SPECIFIC);
}

// Used by Sensors to report new raw ADC sample
void
trigger_analog_update(struct trigger_analog *ta, int32_t sample)
{
    // Check homing is active
    if (!ta)
        return;
    uint8_t flags = ta->flags;
    if (!(flags & TA_CAN_TRIGGER))
        return;

    // Check if homing has started
    uint32_t time = timer_read_time();
    if ((flags & TA_AWAIT_HOMING) && timer_is_before(time, ta->homing_clock))
        return;
    flags &= ~TA_AWAIT_HOMING;

    // Reset the sensor timeout checking
    monitor_note_activity(ta);

    // Check that raw value is in range
    if (sample < ta->raw_min || sample > ta->raw_max) {
        cancel_homing(ta, TE_RAW_RANGE);
        return;
    }

    // Optional Creality V3 SE PRTouch path uses raw HX711 counts
    // relative to the probe tare. When enabled it owns the trigger
    // decision; the generic force trigger remains disabled.
    if (ta->prtouch_enabled) {
        int32_t prtouch_value = sample - ta->prtouch_tare_counts;
        prtouch_add_sample(ta, prtouch_value);

        if (prtouch_check_trigger(ta)) {
            trsync_do_trigger(ta->ts, ta->trigger_reason);
            flags = 0;
            ta->homing_clock = time;
        }

        ta->flags = flags;
        return;
    }

    // Perform filtering
    int32_t filtered_value = sample;
    int ret = sos_filter_apply(ta->sf, &filtered_value);
    if (ret) {
        cancel_homing(ta, TE_OVERFLOW);
        return;
    }

    // Check if this is a "trigger"
    ret = check_trigger(ta, time, filtered_value);
    if (ret) {
        trsync_do_trigger(ta->ts, ta->trigger_reason);
        flags = 0;
        ta->homing_clock = time;
    }

    ta->flags = flags;
}

// Create a trigger_analog
void
command_config_trigger_analog(uint32_t *args)
{
    struct trigger_analog *ta = oid_alloc(
        args[0], command_config_trigger_analog, sizeof(*ta));
    ta->prtouch_enabled = 0;
    ta->prtouch_min_hold = 1000;
    ta->prtouch_max_hold = 1500;
    ta->prtouch_tare_counts = 0;
    prtouch_reset(ta);
    ta->sf = sos_filter_oid_lookup(args[1]);
}
DECL_COMMAND(command_config_trigger_analog
             , "config_trigger_analog oid=%c sos_filter_oid=%c");

// Lookup a trigger_analog
struct trigger_analog *
trigger_analog_oid_lookup(uint8_t oid)
{
    return oid_lookup(oid, command_config_trigger_analog);
}

// Set valid raw range
void
command_trigger_analog_set_raw_range(uint32_t *args)
{
    struct trigger_analog *ta = trigger_analog_oid_lookup(args[0]);
    ta->raw_min = args[1];
    ta->raw_max = args[2];
}
DECL_COMMAND(command_trigger_analog_set_raw_range,
    "trigger_analog_set_raw_range oid=%c raw_min=%i raw_max=%i");

// Set the triggering type and value
void
command_trigger_analog_set_trigger(uint32_t *args)
{
    struct trigger_analog *ta = trigger_analog_oid_lookup(args[0]);
    ta->trigger_type = args[1];
    ta->trigger_value = args[2];
}
DECL_COMMAND(command_trigger_analog_set_trigger, "trigger_analog_set_trigger"
    " oid=%c trigger_analog_type=%c trigger_value=%i");

// Configure optional Creality-compatible PRTouch waveform triggering.
// min_hold/max_hold remain in Creality filtered sensor units.
void
command_trigger_analog_set_prtouch(uint32_t *args)
{
    struct trigger_analog *ta = trigger_analog_oid_lookup(args[0]);
    ta->prtouch_enabled = args[1];
    ta->prtouch_tare_counts = args[2];
    ta->prtouch_min_hold = args[3];
    ta->prtouch_max_hold = args[4];
    prtouch_reset(ta);
}
DECL_COMMAND(command_trigger_analog_set_prtouch,
    "trigger_analog_set_prtouch oid=%c enabled=%c tare_counts=%i"
    " min_hold=%u max_hold=%u");

// Home an axis
void
command_trigger_analog_home(uint32_t *args)
{
    struct trigger_analog *ta = trigger_analog_oid_lookup(args[0]);
    sched_del_timer(&ta->time);
    prtouch_reset(ta);
    ta->monitor_ticks = args[5];
    if (!ta->monitor_ticks) {
        ta->flags = 0;
        ta->ts = NULL;
        return;
    }
    ta->ts = trsync_oid_lookup(args[1]);
    ta->trigger_reason = args[2];
    ta->error_reason = args[3];
    ta->time.waketime = ta->homing_clock = args[4];
    ta->monitor_max = args[6];
    ta->monitor_count = 0;
    ta->time.func = monitor_event;
    ta->flags = TA_AWAIT_HOMING | TA_CAN_TRIGGER;
    trigger_reset(ta);
    sched_add_timer(&ta->time);
}
DECL_COMMAND(command_trigger_analog_home,
             "trigger_analog_home oid=%c trsync_oid=%c trigger_reason=%c"
             " error_reason=%c clock=%u monitor_ticks=%u monitor_max=%u");

void
command_trigger_analog_query_state(uint32_t *args)
{
    uint8_t oid = args[0];
    struct trigger_analog *ta = trigger_analog_oid_lookup(args[0]);
    sendf("trigger_analog_state oid=%c homing=%c homing_clock=%u"
          , oid, !!(ta->flags & TA_CAN_TRIGGER), ta->homing_clock);
}
DECL_COMMAND(command_trigger_analog_query_state
             , "trigger_analog_query_state oid=%c");
