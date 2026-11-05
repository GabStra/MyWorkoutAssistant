/*
 * Parcelable TrackerUserProfile of Samsung Health Platform (HealthPlatform 1.7.00.05).
 *
 * Copied verbatim from the jadx decompile of com.samsung.android.service.health
 * (class com.samsung.android.service.health.tracking.data.TrackerUserProfile, creator
 * extracted by jadx into data/c.java). The parcel layout MUST stay byte-compatible with
 * the service: float height, float weight, int gender, int age.
 */
package com.samsung.android.service.health.tracking.data;

import android.os.Parcel;
import android.os.Parcelable;

public final class TrackerUserProfile implements Parcelable {
    public static final Parcelable.Creator<TrackerUserProfile> CREATOR = new Parcelable.Creator<TrackerUserProfile>() {
        @Override
        public TrackerUserProfile createFromParcel(Parcel parcel) {
            return new TrackerUserProfile(parcel);
        }

        @Override
        public TrackerUserProfile[] newArray(int size) {
            return new TrackerUserProfile[size];
        }
    };

    private final float height;
    private final float weight;
    private final int gender;
    private final int age;

    public static class Builder {
        private float height = -1.0f;
        private float weight = -1.0f;
        private int gender = -1;
        private int age = -1;

        public Builder setHeight(float height) {
            this.height = height;
            return this;
        }

        public Builder setWeight(float weight) {
            this.weight = weight;
            return this;
        }

        public Builder setGender(int gender) {
            this.gender = gender;
            return this;
        }

        public Builder setAge(int age) {
            this.age = age;
            return this;
        }

        public TrackerUserProfile build() {
            return new TrackerUserProfile(this.height, this.weight, this.gender, this.age);
        }
    }

    public TrackerUserProfile(float height, float weight, int gender, int age) {
        this.height = height;
        this.weight = weight;
        this.gender = gender;
        this.age = age;
    }

    private TrackerUserProfile(Parcel parcel) {
        this.height = parcel.readFloat();
        this.weight = parcel.readFloat();
        this.gender = parcel.readInt();
        this.age = parcel.readInt();
    }

    public float getHeight() {
        return this.height;
    }

    public float getWeight() {
        return this.weight;
    }

    public int getGender() {
        return this.gender;
    }

    public int getAge() {
        return this.age;
    }

    @Override
    public int describeContents() {
        return 0;
    }

    @Override
    public void writeToParcel(Parcel parcel, int flags) {
        parcel.writeFloat(this.height);
        parcel.writeFloat(this.weight);
        parcel.writeInt(this.gender);
        parcel.writeInt(this.age);
    }
}
