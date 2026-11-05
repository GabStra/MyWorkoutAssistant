/*
 * DataPoint of Samsung Health Platform — copied verbatim from the jadx decompile
 * (com.samsung.android.service.health.tracking.data.DataPoint). A timestamped map of
 * ValueKey -> Value produced by ServiceDataPoint.convert*ToDataPoint().
 */
package com.samsung.android.service.health.tracking.data;

import java.util.Map;

public class DataPoint {
    private long timestamp;
    private final Map<ValueKey, Value> values;

    public DataPoint(Map<ValueKey, Value> values) {
        this.values = values;
    }

    void setTimestamp(long timestamp) {
        this.timestamp = timestamp;
    }

    public long getTimestamp() {
        return this.timestamp;
    }

    public <T> T getValue(ValueKey<T> valueKey) {
        Value value = this.values.get(valueKey);
        @SuppressWarnings("unchecked")
        T result = value == null ? null : (T) value.value;
        return result;
    }
}
