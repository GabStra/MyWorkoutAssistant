/*
 * Parcelable ServiceDataPoint of Samsung Health Platform (HealthPlatform 1.7.00.05).
 *
 * Copied verbatim from the jadx decompile of com.samsung.android.service.health
 * (class com.samsung.android.service.health.tracking.data.ServiceDataPoint, creator
 * extracted by jadx into data/a.java). Wire layout: long timestamp (epoch millis),
 * then List<ServiceValue> written with Parcel.writeList (self-describing).
 *
 * The convert*ToDataPoint() methods below are Samsung's own ServiceDataPoint ->
 * DataPoint(ValueKey) decoders; they are the authoritative per-tracker value list
 * layouts for this firmware and are used by SamsungHealthClientImpl.
 */
package com.samsung.android.service.health.tracking.data;

import android.os.Parcel;
import android.os.Parcelable;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;

public final class ServiceDataPoint implements Parcelable {
    public static final Parcelable.Creator<ServiceDataPoint> CREATOR = new Parcelable.Creator<ServiceDataPoint>() {
        @Override
        public ServiceDataPoint createFromParcel(Parcel parcel) {
            return new ServiceDataPoint(parcel);
        }

        @Override
        public ServiceDataPoint[] newArray(int size) {
            return new ServiceDataPoint[size];
        }
    };

    private static final List<String> MF_BIA_FREQUENCIES = Collections.unmodifiableList(
            java.util.Arrays.asList("5K", "10K", "50K", "250K"));

    private final long timestamp;
    private final List<ServiceValue> values;

    public static class Builder {
        private long timestamp;
        private List<ServiceValue> values = Collections.emptyList();

        public Builder setTimeStamp(long timestamp) {
            this.timestamp = timestamp;
            return this;
        }

        public Builder setValues(List<ServiceValue> values) {
            this.values = values;
            return this;
        }

        public ServiceDataPoint build() {
            return new ServiceDataPoint(this.timestamp, this.values);
        }
    }

    public ServiceDataPoint(long timestamp, List<ServiceValue> values) {
        this.timestamp = timestamp;
        this.values = values;
    }

    private ServiceDataPoint(Parcel parcel) {
        this.timestamp = parcel.readLong();
        ArrayList<ServiceValue> list = new ArrayList<>();
        parcel.readList(list, ServiceValue.class.getClassLoader());
        this.values = list;
    }

    public static Builder builder() {
        return new Builder();
    }

    public final List<ServiceValue> getServiceValue() {
        return this.values;
    }

    public long getTimeStamp() {
        return this.timestamp;
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel parcel, int flags) {
        parcel.writeLong(this.timestamp);
        parcel.writeList(this.values);
    }

    // ---------------------------------------------------------------------------------------------
    // Samsung's own decoders: ServiceDataPoint -> DataPoint keyed by ValueKey. These encode the
    // exact position of each field in the values list, as written by the matching server-side
    // tracker in the same APK. Bodies are semantically identical to the decompile; the MfBia
    // reflection helper is inlined.
    // ---------------------------------------------------------------------------------------------

    public DataPoint convertAccToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.AccelerometerSet.ACCELEROMETER_X, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.AccelerometerSet.ACCELEROMETER_Y, new Value<>(v.get(1).getIntegerValue()));
        map.put(ValueKey.AccelerometerSet.ACCELEROMETER_Z, new Value<>(v.get(2).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertBiaToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.BiaSet.STATUS, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.BiaSet.BODY_FAT_RATIO, new Value<>(v.get(1).getFloatValue()));
        map.put(ValueKey.BiaSet.BODY_FAT_MASS, new Value<>(v.get(2).getFloatValue()));
        map.put(ValueKey.BiaSet.TOTAL_BODY_WATER, new Value<>(v.get(3).getFloatValue()));
        map.put(ValueKey.BiaSet.SKELETAL_MUSCLE_RATIO, new Value<>(v.get(4).getFloatValue()));
        map.put(ValueKey.BiaSet.SKELETAL_MUSCLE_MASS, new Value<>(v.get(5).getFloatValue()));
        map.put(ValueKey.BiaSet.BASAL_METABOLIC_RATE, new Value<>(v.get(6).getFloatValue()));
        map.put(ValueKey.BiaSet.FAT_FREE_RATIO, new Value<>(v.get(7).getFloatValue()));
        map.put(ValueKey.BiaSet.FAT_FREE_MASS, new Value<>(v.get(8).getFloatValue()));
        map.put(ValueKey.BiaSet.PROGRESS, new Value<>(v.get(9).getFloatValue()));
        map.put(ValueKey.BiaSet.BODY_IMPEDANCE_MAGNITUDE, new Value<>(v.get(10).getFloatValue()));
        map.put(ValueKey.BiaSet.BODY_IMPEDANCE_DEGREE, new Value<>(v.get(11).getFloatValue()));
        return dataPoint(map);
    }

    public DataPoint convertEcgToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.EcgSet.PPG_GREEN, new Value<>(v.get(1).getIntegerValue()));
        map.put(ValueKey.EcgSet.LEAD_OFF, new Value<>(v.get(2).getIntegerValue()));
        map.put(ValueKey.EcgSet.SEQUENCE, new Value<>(v.get(3).getIntegerValue()));
        map.put(ValueKey.EcgSet.ECG_MV, new Value<>(v.get(0).getFloatValue()));
        map.put(ValueKey.EcgSet.MAX_THRESHOLD_MV, new Value<>(v.get(4).getFloatValue()));
        map.put(ValueKey.EcgSet.MIN_THRESHOLD_MV, new Value<>(v.get(5).getFloatValue()));
        return dataPoint(map);
    }

    public DataPoint convertEdaToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.EdaSet.SKIN_CONDUCTANCE, new Value<>(v.get(0).getFloatValue()));
        map.put(ValueKey.EdaSet.STATUS, new Value<>(v.get(1).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertHrToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        int heartRate = getServiceValue().get(0).getIntegerValue();
        int heartRateStatus = getServiceValue().get(2).getIntegerValue();
        int ibiCount = getServiceValue().get(3).getIntegerValue();
        ArrayList<Integer> ibiList = new ArrayList<>();
        ArrayList<Integer> ibiStatusList = new ArrayList<>();
        for (int i = 0; i < ibiCount * 2; i += 2) {
            ibiList.add(getServiceValue().get(i + 4).getIntegerValue());
            ibiStatusList.add(getServiceValue().get(i + 5).getIntegerValue());
        }
        map.put(ValueKey.HeartRateSet.HEART_RATE, new Value<>(heartRate));
        map.put(ValueKey.HeartRateSet.IBI_LIST, new Value<>(ibiList));
        map.put(ValueKey.HeartRateSet.IBI_STATUS_LIST, new Value<>(ibiStatusList));
        map.put(ValueKey.HeartRateSet.HEART_RATE_STATUS, new Value<>(heartRateStatus));
        return dataPoint(map);
    }

    public DataPoint convertIrToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.PpgIrSet.PPG_IR, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.PpgIrSet.STATUS, new Value<>(v.get(1).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertMfBiaToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        int i = 0;
        while (true) {
            if (i >= MF_BIA_FREQUENCIES.size()) {
                map.put(ValueKey.MfBiaSet.STATUS, new Value<>(getServiceValue().get(8).getIntegerValue()));
                map.put(ValueKey.MfBiaSet.PROGRESS, new Value<>(getServiceValue().get(9).getFloatValue()));
                return dataPoint(map);
            }
            String frequency = MF_BIA_FREQUENCIES.get(i);
            int index = i * 2;
            map.put(mfBiaKey(frequency, true), new Value<>(getServiceValue().get(index).getFloatValue()));
            map.put(mfBiaKey(frequency, false), new Value<>(getServiceValue().get(index + 1).getFloatValue()));
            i++;
        }
    }

    @SuppressWarnings("unchecked")
    private static ValueKey<Float> mfBiaKey(String frequency, boolean magnitude) {
        String name = "BODY_IMPEDANCE_" + (magnitude ? "MAGNITUDE" : "PHASE") + "_" + frequency;
        try {
            return (ValueKey<Float>) ValueKey.MfBiaSet.class.getDeclaredField(name).get(null);
        } catch (Exception unused) {
            return null;
        }
    }

    public DataPoint convertPpgGreenToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.PpgGreenSet.PPG_GREEN, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.PpgGreenSet.STATUS, new Value<>(v.get(1).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertPpgRedToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.PpgRedSet.PPG_RED, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.PpgRedSet.STATUS, new Value<>(v.get(2).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertPpgToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.PpgSet.PPG_GREEN, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.PpgSet.GREEN_STATUS, new Value<>(v.get(1).getIntegerValue()));
        map.put(ValueKey.PpgSet.PPG_RED, new Value<>(v.get(2).getIntegerValue()));
        map.put(ValueKey.PpgSet.RED_STATUS, new Value<>(v.get(3).getIntegerValue()));
        map.put(ValueKey.PpgSet.PPG_IR, new Value<>(v.get(4).getIntegerValue()));
        map.put(ValueKey.PpgSet.IR_STATUS, new Value<>(v.get(5).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertSkinTemperatureToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.SkinTemperatureSet.OBJECT_TEMPERATURE, new Value<>(v.get(0).getFloatValue()));
        map.put(ValueKey.SkinTemperatureSet.AMBIENT_TEMPERATURE, new Value<>(v.get(1).getFloatValue()));
        map.put(ValueKey.SkinTemperatureSet.STATUS, new Value<>(v.get(2).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertSpO2ToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.SpO2Set.STATUS, new Value<>(v.get(0).getIntegerValue()));
        map.put(ValueKey.SpO2Set.SPO2, new Value<>(v.get(1).getIntegerValue()));
        map.put(ValueKey.SpO2Set.HEART_RATE, new Value<>(v.get(2).getIntegerValue()));
        map.put(ValueKey.SpO2Set.ACCURACY_FLAG, new Value<>(v.get(3).getIntegerValue()));
        return dataPoint(map);
    }

    public DataPoint convertSweatLossToDataPoint() {
        HashMap<ValueKey, Value> map = new HashMap<>();
        List<ServiceValue> v = getServiceValue();
        map.put(ValueKey.SweatLossSet.SWEAT_LOSS, new Value<>(v.get(0).getFloatValue()));
        map.put(ValueKey.SweatLossSet.STATUS, new Value<>(v.get(1).getIntegerValue()));
        return dataPoint(map);
    }

    private static DataPoint dataPoint(HashMap<ValueKey, Value> map) {
        return new DataPoint(map);
    }
}
