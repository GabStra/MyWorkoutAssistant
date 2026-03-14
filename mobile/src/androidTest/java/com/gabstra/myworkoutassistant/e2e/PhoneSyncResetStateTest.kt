package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.shared.AppDatabase
import kotlinx.coroutines.runBlocking
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class PhoneSyncResetStateTest {

    @Test
    fun clearPhoneWorkoutHistoryState() {
        runBlocking {
            val context = ApplicationProvider.getApplicationContext<android.content.Context>()
            val db = AppDatabase.getDatabase(context)

            db.workoutHistoryDao().deleteAll()
            db.setHistoryDao().deleteAll()
            db.workoutRecordDao().deleteAll()
            db.exerciseInfoDao().deleteAll()
            db.exerciseSessionProgressionDao().deleteAll()

            WorkManager.getInstance(context).cancelUniqueWork("mobile_sync_to_watch")
        }
    }
}
