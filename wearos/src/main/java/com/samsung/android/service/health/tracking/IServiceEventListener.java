/*
 * Service -> client callback binder interface of Samsung Health Platform
 * (HealthPlatform 1.7.00.05, Galaxy Watch 7 SM-L310).
 *
 * Reconstructed from the jadx decompile of com.samsung.android.service.health
 * (classes com.samsung.android.service.health.tracking.IServiceEventListener plus the
 * obfuscated companions h [Stub], g [Proxy] and i [typed-list helpers], which are
 * verbatim AIDL-compiler output). A client implements Stub to receive tracker data.
 * Descriptor, transaction codes and parcel field order are byte-compatible with the
 * on-device service.
 */
package com.samsung.android.service.health.tracking;

import android.os.Binder;
import android.os.IBinder;
import android.os.IInterface;
import android.os.Parcel;
import android.os.Parcelable;
import android.os.RemoteException;

import com.samsung.android.service.health.tracking.data.ServiceDataPoint;

import java.util.List;

public interface IServiceEventListener extends IInterface {
    String DESCRIPTOR = "com.samsung.android.service.health.tracking.IServiceEventListener";

    /** Transaction code 1. Delivered whenever the service has new tracker samples. */
    void onDataUpdated(List<ServiceDataPoint> dataPoints) throws RemoteException;

    /** Transaction code 2. errorCode is HealthTracker.TrackerError.ordinal() (0=PERMISSION_ERROR, 1=SDK_POLICY_ERROR). */
    void onThrowException(int errorCode) throws RemoteException;

    /** Transaction code 3. */
    void onFlushCompleted() throws RemoteException;

    /** Local binder implementation (client side extends this). */
    abstract class Stub extends Binder implements IServiceEventListener {
        static final int TRANSACTION_onDataUpdated = 1;
        static final int TRANSACTION_onThrowException = 2;
        static final int TRANSACTION_onFlushCompleted = 3;

        public Stub() {
            attachInterface(this, DESCRIPTOR);
        }

        public static IServiceEventListener asInterface(IBinder obj) {
            if (obj == null) {
                return null;
            }
            IInterface iin = obj.queryLocalInterface(DESCRIPTOR);
            if (iin != null && iin instanceof IServiceEventListener) {
                return (IServiceEventListener) iin;
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
            if (code == 1) {
                List<ServiceDataPoint> arg0 = data.createTypedArrayList(ServiceDataPoint.CREATOR);
                onDataUpdated(arg0);
                reply.writeNoException();
                return true;
            } else if (code == 2) {
                int arg0 = data.readInt();
                onThrowException(arg0);
                reply.writeNoException();
                return true;
            } else if (code == 3) {
                onFlushCompleted();
                reply.writeNoException();
                return true;
            }
            return super.onTransact(code, data, reply, flags);
        }

        static <T extends Parcelable> void writeTypedList(Parcel parcel, List<T> list, int flags) {
            if (list == null) {
                parcel.writeInt(-1);
                return;
            }
            int size = list.size();
            parcel.writeInt(size);
            for (int i = 0; i < size; i++) {
                writeTypedObject(parcel, list.get(i), flags);
            }
        }

        static <T extends Parcelable> void writeTypedObject(Parcel parcel, T value, int flags) {
            if (value == null) {
                parcel.writeInt(0);
            } else {
                parcel.writeInt(1);
                value.writeToParcel(parcel, flags);
            }
        }
    }

    /** Outgoing proxy (used by the service when it calls the client's listener). */
    class Proxy implements IServiceEventListener {
        private final IBinder mRemote;

        Proxy(IBinder remote) {
            mRemote = remote;
        }

        @Override
        public IBinder asBinder() {
            return mRemote;
        }

        @Override
        public void onDataUpdated(List<ServiceDataPoint> dataPoints) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                Stub.writeTypedList(data, dataPoints, 0);
                mRemote.transact(Stub.TRANSACTION_onDataUpdated, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void onFlushCompleted() throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                mRemote.transact(Stub.TRANSACTION_onFlushCompleted, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }

        @Override
        public void onThrowException(int errorCode) throws RemoteException {
            Parcel data = Parcel.obtain();
            Parcel reply = Parcel.obtain();
            try {
                data.writeInterfaceToken(DESCRIPTOR);
                data.writeInt(errorCode);
                mRemote.transact(Stub.TRANSACTION_onThrowException, data, reply, 0);
                reply.readException();
            } finally {
                reply.recycle();
                data.recycle();
            }
        }
    }
}
