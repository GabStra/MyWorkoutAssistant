/*
 * HealthTrackerType of Samsung Health Platform — copied verbatim from the jadx decompile
 * (com.samsung.android.service.health.tracking.data.HealthTrackerType). Declaration order
 * matters: the SDK's switch tables key off ordinals. The wire protocol uses the STRING
 * form (see HealthTrackerTypeStrings mapping in SamsungHealthClientImpl):
 * several enum constants share one server tracker string.
 */
package com.samsung.android.service.health.tracking.data;

public enum HealthTrackerType {
    PPG_GREEN,
    PPG_CONTINUOUS,
    PPG_RED,
    PPG_IR,
    PPG_ON_DEMAND,
    HEART_RATE,
    HEART_RATE_CONTINUOUS,
    ECG,
    ECG_ON_DEMAND,
    ACCELEROMETER,
    ACCELEROMETER_CONTINUOUS,
    BIA,
    BIA_ON_DEMAND,
    SWEAT_LOSS,
    SPO2,
    SPO2_ON_DEMAND,
    SKIN_TEMPERATURE,
    SKIN_TEMPERATURE_ON_DEMAND,
    SKIN_TEMPERATURE_CONTINUOUS,
    EDA_CONTINUOUS,
    MFBIA_ON_DEMAND
}
