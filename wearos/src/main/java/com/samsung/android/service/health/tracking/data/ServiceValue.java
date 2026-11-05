/*
 * Parcelable ServiceValue of Samsung Health Platform (HealthPlatform 1.7.00.05).
 *
 * Copied verbatim from the jadx decompile of com.samsung.android.service.health
 * (class com.samsung.android.service.health.tracking.data.ServiceValue, creator extracted
 * by jadx into data/b.java). Wire layout: int integerValue, float floatValue, long
 * longValue. A ServiceValue is a tagged union: exactly one field is meaningful per data
 * point position. The class name must remain
 * com.samsung.android.service.health.tracking.data.ServiceValue because
 * ServiceDataPoint marshals its value list with Parcel.writeList/readList, which sends
 * the fully-qualified class name over the binder.
 */
package com.samsung.android.service.health.tracking.data;

import android.os.Parcel;
import android.os.Parcelable;

public final class ServiceValue implements Parcelable {
    public static final Parcelable.Creator<ServiceValue> CREATOR = new Parcelable.Creator<ServiceValue>() {
        @Override
        public ServiceValue createFromParcel(Parcel parcel) {
            return new ServiceValue(parcel);
        }

        @Override
        public ServiceValue[] newArray(int size) {
            return new ServiceValue[size];
        }
    };

    private int integerValue;
    private float floatValue;
    private long longValue;

    public static class Builder<T> {
        private float floatValue;
        private int integerValue;
        private long longValue;

        public Builder<T> setFloatValue(float value) {
            this.floatValue = value;
            return this;
        }

        public Builder<T> setIntegerValue(int value) {
            this.integerValue = value;
            return this;
        }

        public Builder<T> setLongValue(long value) {
            this.longValue = value;
            return this;
        }

        @SuppressWarnings("unchecked")
        public Builder<T> setAnyValue(T value) {
            if (value.getClass().equals(Integer.class)) {
                this.integerValue = ((Integer) value).intValue();
                return this;
            }
            if (value.getClass().equals(Float.class)) {
                this.floatValue = ((Float) value).floatValue();
                return this;
            }
            if (value.getClass().equals(Long.class)) {
                this.longValue = ((Long) value).longValue();
            }
            return this;
        }

        public ServiceValue build() {
            return new ServiceValue(this.integerValue, this.floatValue, this.longValue);
        }
    }

    public ServiceValue(int integerValue, float floatValue, long longValue) {
        this.integerValue = integerValue;
        this.floatValue = floatValue;
        this.longValue = longValue;
    }

    public static Builder<Void> builder() {
        return new Builder<>();
    }

    public final float getFloatValue() {
        return this.floatValue;
    }

    public final int getIntegerValue() {
        return this.integerValue;
    }

    public final void readFromParcel(Parcel parcel) {
        this.integerValue = parcel.readInt();
        this.floatValue = parcel.readFloat();
        this.longValue = parcel.readLong();
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel parcel, int flags) {
        parcel.writeInt(this.integerValue);
        parcel.writeFloat(this.floatValue);
        parcel.writeLong(this.longValue);
    }

    private ServiceValue(Parcel parcel) {
        readFromParcel(parcel);
    }
}
