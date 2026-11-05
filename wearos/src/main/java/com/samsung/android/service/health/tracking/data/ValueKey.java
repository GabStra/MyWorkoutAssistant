/*
 * ValueKey<T> of Samsung Health Platform — copied verbatim from the jadx decompile
 * (com.samsung.android.service.health.tracking.data.ValueKey). Identity-based keys used
 * with ServiceDataPoint.convert*ToDataPoint() / DataPoint.getValue().
 */
package com.samsung.android.service.health.tracking.data;

import java.util.List;

public class ValueKey<T> {

    public static class AccelerometerSet {
        public static final ValueKey<Integer> ACCELEROMETER_X = new ValueKey<>();
        public static final ValueKey<Integer> ACCELEROMETER_Y = new ValueKey<>();
        public static final ValueKey<Integer> ACCELEROMETER_Z = new ValueKey<>();
    }

    public static class BiaSet {
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
        public static final ValueKey<Float> BODY_FAT_RATIO = new ValueKey<>();
        public static final ValueKey<Float> BODY_FAT_MASS = new ValueKey<>();
        public static final ValueKey<Float> TOTAL_BODY_WATER = new ValueKey<>();
        public static final ValueKey<Float> SKELETAL_MUSCLE_RATIO = new ValueKey<>();
        public static final ValueKey<Float> SKELETAL_MUSCLE_MASS = new ValueKey<>();
        public static final ValueKey<Float> BASAL_METABOLIC_RATE = new ValueKey<>();
        public static final ValueKey<Float> FAT_FREE_RATIO = new ValueKey<>();
        public static final ValueKey<Float> FAT_FREE_MASS = new ValueKey<>();
        public static final ValueKey<Float> PROGRESS = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_MAGNITUDE = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_DEGREE = new ValueKey<>();
    }

    public static class EcgSet {
        public static final ValueKey<Integer> LEAD_OFF = new ValueKey<>();
        public static final ValueKey<Integer> SEQUENCE = new ValueKey<>();
        public static final ValueKey<Integer> PPG_GREEN = new ValueKey<>();
        public static final ValueKey<Float> ECG_MV = new ValueKey<>();
        public static final ValueKey<Float> MAX_THRESHOLD_MV = new ValueKey<>();
        public static final ValueKey<Float> MIN_THRESHOLD_MV = new ValueKey<>();
    }

    public static class EdaSet {
        public static final ValueKey<Float> SKIN_CONDUCTANCE = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
    }

    public static class HeartRateSet {
        public static final ValueKey<Integer> HEART_RATE = new ValueKey<>();
        public static final ValueKey<List<Integer>> IBI_LIST = new ValueKey<>();
        public static final ValueKey<List<Integer>> IBI_STATUS_LIST = new ValueKey<>();
        public static final ValueKey<Integer> HEART_RATE_STATUS = new ValueKey<>();
    }

    public static class MfBiaSet {
        public static final ValueKey<Float> BODY_IMPEDANCE_MAGNITUDE_5K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_PHASE_5K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_MAGNITUDE_10K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_PHASE_10K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_MAGNITUDE_50K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_PHASE_50K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_MAGNITUDE_250K = new ValueKey<>();
        public static final ValueKey<Float> BODY_IMPEDANCE_PHASE_250K = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
        public static final ValueKey<Float> PROGRESS = new ValueKey<>();
    }

    @Deprecated
    public static class PpgGreenSet {
        public static final ValueKey<Integer> PPG_GREEN = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
    }

    @Deprecated
    public static class PpgIrSet {
        public static final ValueKey<Integer> PPG_IR = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
    }

    @Deprecated
    public static class PpgRedSet {
        public static final ValueKey<Integer> PPG_RED = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
    }

    public static class PpgSet {
        public static final ValueKey<Integer> PPG_GREEN = new ValueKey<>();
        public static final ValueKey<Integer> GREEN_STATUS = new ValueKey<>();
        public static final ValueKey<Integer> PPG_IR = new ValueKey<>();
        public static final ValueKey<Integer> IR_STATUS = new ValueKey<>();
        public static final ValueKey<Integer> PPG_RED = new ValueKey<>();
        public static final ValueKey<Integer> RED_STATUS = new ValueKey<>();
    }

    public static class SkinTemperatureSet {
        public static final ValueKey<Float> OBJECT_TEMPERATURE = new ValueKey<>();
        public static final ValueKey<Float> AMBIENT_TEMPERATURE = new ValueKey<>();
        public static ValueKey<Integer> STATUS = new ValueKey<>();
    }

    public static class SpO2Set {
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
        public static final ValueKey<Integer> SPO2 = new ValueKey<>();
        public static final ValueKey<Integer> HEART_RATE = new ValueKey<>();
        public static final ValueKey<Integer> ACCURACY_FLAG = new ValueKey<>();
    }

    public static class SweatLossSet {
        public static final ValueKey<Float> SWEAT_LOSS = new ValueKey<>();
        public static final ValueKey<Integer> STATUS = new ValueKey<>();
    }
}
