/*
 * Client -> service binder interface of Samsung Health Platform (HealthPlatform 1.7.00.05,
 * Galaxy Watch 7 SM-L310).
 *
 * Reconstructed from the jadx decompile of com.samsung.android.service.health
 * (classes com.samsung.android.service.health.tracking.IClientEventListener$Stub and
 * its obfuscated companions f/d/e). The decompiled Stub/Proxy code is verbatim
 * AIDL-compiler output, so this file reconstitutes it as the nested Stub/Proxy
 * structure AIDL would have produced. Descriptor, transaction codes and parcel
 * field order are byte-compatible with the on-device service.
 */
package com.samsung.android.service.health.tracking;

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.Parcel;
import android.os.RemoteException;

import com.samsung.android.service.health.tracking.data.TrackerUserProfile;

import java.util.List;

public interface IClientEventListener extends IInterface {
    String DESCRIPTOR = "com.samsung.android.service.health.tracking.IClientEventListener";

    /** Server message MESSAGE_CREATE_TRACKER (handler what = 0). Transaction code 1. */
    void createHealthTracker(String appId, String trackertype, TrackerUserProfile userProfile, String exerciseType) throws RemoteException;

    /** Server message MESSAGE_SET_LISTENER (handler what = 1). Transaction code 2. */
    void setEventListener(String appId, String trackertype, IServiceEventListener listener) throws RemoteException;

    /** Server message MESSAGE_UNSET_LISTENER (handler what = 2). Transaction code 3. */
    void unsetEventListener(String appId, String trackertype) throws RemoteException;

    /** Server message MESSAGE_FLUSH (handler what = 3). Transaction code 4. */
    void flush(String appId, String trackertype) throws RemoteException;

    /** Returns the capability list, e.g. ["HEART_RATE", "ECG", ...]. Transaction code 5. */
    List<String> getSupportedHealthTrackerTypes() throws RemoteException;

    /** Server message MESSAGE_EXERCISE_STATE (handler what = 4). Transaction code 6. */
    void setExerciseState(String appId, String trackertype, String exerciseState) throws RemoteException;

    /** Server message MESSAGE_EXERCISE_DATA (handler what = 5). Transaction code 7. */
    void setExerciseData(String appId, String trackertype, String dataType, float[] data, long[] timestamp) throws RemoteException;

    /** Server message MESSAGE_SET_PPG_TYPE (handler what = 6). Transaction code 8. */
    void setPpgType(String appId, String trackertype, List<String> ppgTypes) throws RemoteException;

    /**
     * Local binder implementation of the server side. Not used by clients, kept for
     * wire-format completeness.
     */
    abstract class Stub extends Binder implements IClientEventListener {
        static final int TRANSACTION_createHealthTracker = 1;
        static final int TRANSACTION_setEventListener = 2;
        static final int TRANSACTION_unsetEventListener = 3;
        static final int TRANSACTION_flush = 4;
        static final int TRANSACTION_getSupportedHealthTrackerTypes = 5;
        static final int TRANSACTION_setExerciseState = 6;
        static final int TRANSACTION_setExerciseData = 7;
        static final int TRANSACTION_setPpgType = 8;

        public Stub() {
            attachInterface(this, DESCRIPTOR);
        }

        public static IClientEventListener asInterface(IBinder obj) {
            if (obj == null) {
                return null;
            }
            IInterface iin = obj.queryLocalInterface(DESCRIPTOR);
            if (iin != null && iin instanceof IClientEventListener) {
                return (IClientEventListener) iin;
            }
            return new Proxy(obj);
        }

        @Override
        public IBinder asBinder() {
            return this;
        }

        @Override
        public boolean onTransact(int code, Parcel data, Parcel reply, int flags) throws RemoteException {
            String descriptor = DESCRIPTOR;
            if (code >= 1 && code <= 16777215) {
                data.enforceInterface(descriptor);
            }
            if (code == 1598968902) {
                reply.writeString(descriptor);
                return true;
            }
            switch (code) {
                case 1: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    TrackerUserProfile arg2 = readTypedObject(data, TrackerUserProfile.CREATOR);
                    String arg3 = data.readString();
                    createHealthTracker(arg0, arg1, arg2, arg3);
                    reply.writeNoException();
                    return true;
                }
                case 2: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    IServiceEventListener arg2 = IServiceEventListener.Stub.asInterface(data.readStrongBinder());
                    setEventListener(arg0, arg1, arg2);
                    reply.writeNoException();
                    return true;
                }
                case 3: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    unsetEventListener(arg0, arg1);
                    reply.writeNoException();
                    return true;
                }
                case 4: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    flush(arg0, arg1);
                    reply.writeNoException();
                    return true;
                }
                case 5: {
                    List<String> result = getSupportedHealthTrackerTypes();
                    reply.writeNoException();
                    reply.writeStringList(result);
                    return true;
                }
                case 6: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    String arg2 = data.readString();
                    setExerciseState(arg0, arg1, arg2);
                    reply.writeNoException();
                    return true;
                }
                case 7: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    String arg2 = data.readString();
                    float[] arg3 = data.createFloatArray();
                    long[] arg4 = data.createLongArray();
                    setExerciseData(arg0, arg1, arg2, arg3, arg4);
                    reply.writeNoException();
                    return true;
                }
                case 8: {
                    String arg0 = data.readString();
                    String arg1 = data.readString();
                    List<String> arg2 = data.createStringArrayList();
                    setPpgType(arg0, arg1, arg2);
                    reply.writeNoException();
                    return true;
                }
                default: {
                    return super.onTransact(code, data, reply, flags);
                }
            }
        }

        private static <T> T readTypedObject(Parcel parcel, android.os.Parcelable.Creator<T> creator) {
            if (parcel.readInt() != 0) {
                return creator.createFromParcel(parcel);
            }
            return null;
        }

        static <T extends android.os.Parcelable> void writeTypedObject(Parcel parcel, T value, int flags) {
            if (value == null) {
                parcel.writeInt(0);
            } else {
                parcel.writeInt(1);
                value.writeToParcel(parcel, flags);
            }
        }
    }

    /** Outgoing call proxy (the piece a client actually uses). */
    class Proxy implements IClientEventListener {
        private final IBinder mRemote;

        Proxy(IBinder remote) {
            mRemote = remote;
        }

        @Override
        public IBinder asBinder() {
            return mRemote;
        }

        @Override
        public void createHealthTracker(String appId, String trackertype, TrackerUserProfile userProfile, String exerciseType) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                Stub.writeTypedObject(data, userProfile, 0);                data.writeString(exerciseType);
                mRemote.transact(Stub.TRANSACTION_createHealthTracker, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void setEventListener(String appId, String trackertype, IServiceEventListener listener) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                data.writeStrongInterface(listener);
                mRemote.transact(Stub.TRANSACTION_setEventListener, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void unsetEventListener(String appId, String trackertype) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                mRemote.transact(Stub.TRANSACTION_unsetEventListener, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void flush(String appId, String trackertype) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                mRemote.transact(Stub.TRANSACTION_flush, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public List<String> getSupportedHealthTrackerTypes() throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                mRemote.transact(Stub.TRANSACTION_getSupportedHealthTrackerTypes, data, reply, 0);
                reply.readException();
                return reply.createStringArrayList();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void setExerciseState(String appId, String trackertype, String exerciseState) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                data.writeString(exerciseState);
                mRemote.transact(Stub.TRANSACTION_setExerciseState, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void setExerciseData(String appId, String trackertype, String dataType, float[] fArr, long[] jArr) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                data.writeString(dataType);
                data.writeFloatArray(fArr);
                data.writeLongArray(jArr);
                mRemote.transact(Stub.TRANSACTION_setExerciseData, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void setPpgType(String appId, String trackertype, List<String> list) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeString(appId);
                data.writeString(trackertype);
                data.writeStringList(list);
                mRemote.transact(Stub.TRANSACTION_setPpgType, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }
    }

}
