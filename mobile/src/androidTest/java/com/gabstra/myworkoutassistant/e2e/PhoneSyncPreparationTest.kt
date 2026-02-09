package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.uiautomator.UiDevice
import com.gabstra.myworkoutassistant.e2e.driver.PhoneAppDriver
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneSyncPreparationTest {

    @Test
    fun preparePhoneForCrossDeviceSync() = runBlocking {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()
        val device = UiDevice.getInstance(instrumentation)
        val driver = PhoneAppDriver(device, context)

        driver.grantRuntimePermissions(
            android.Manifest.permission.POST_NOTIFICATIONS,
            android.Manifest.permission.ACCESS_FINE_LOCATION,
            android.Manifest.permission.ACCESS_COARSE_LOCATION,
            android.Manifest.permission.BLUETOOTH_SCAN,
            android.Manifest.permission.BLUETOOTH_CONNECT
        )

        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()

        val store = CrossDeviceSyncPhoneWorkoutStoreFixture.createWorkoutStore()
        WorkoutStoreRepository(context.filesDir).saveWorkoutStore(store)

        driver.launchAppFromHome()
        driver.dismissStartupPermissionDialogs()
        driver.syncWithWatchFromMenu()
    }
}
