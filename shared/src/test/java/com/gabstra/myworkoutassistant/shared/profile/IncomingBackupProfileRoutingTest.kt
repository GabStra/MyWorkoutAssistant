package com.gabstra.myworkoutassistant.shared.profile

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import com.google.gson.Gson
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class IncomingBackupProfileRoutingTest {
    private lateinit var context: Context
    private var targetProfileId: String? = null
    private var defaultDatabase: AppDatabase? = null
    private var targetDatabase: AppDatabase? = null

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        Profiles.index(context)
    }

    @After
    fun tearDown() {
        targetDatabase?.close()
        defaultDatabase?.close()
        targetProfileId?.let { Profiles.delete(context, it) }
    }

    @Test
    fun incomingProfileTargetsOwnDatabaseAndPreservesActiveRows() = runBlocking {
        val activeProfileId = Profiles.activeProfileId(context)
        val newProfileId = UUID.randomUUID().toString()
        targetProfileId = newProfileId
        val activeProfile = Profiles.profiles(context).single { it.id == activeProfileId }
        assertTrue(
            Profiles.applyRemoteIndexJson(
                context,
                Gson().toJson(
                    ProfileIndex(
                        activeProfileId = newProfileId,
                        profiles = listOf(
                            activeProfile,
                            UserProfile(newProfileId, "Jennifer"),
                        ),
                    ),
                ),
            ),
        )
        val resolvedTargetId = Profiles.ensureIncomingBackupProfile(
            context,
            payloadProfileId = newProfileId,
            payloadProfileName = "Jennifer",
        )

        assertEquals(newProfileId, resolvedTargetId)
        assertEquals(activeProfileId, Profiles.activeProfileId(context))
        assertEquals("Jennifer", Profiles.profiles(context).single { it.id == newProfileId }.name)
        assertEquals(newProfileId, Profiles.remoteActiveProfileId(context))

        defaultDatabase = AppDatabase.getDatabase(context, activeProfileId)
        targetDatabase = AppDatabase.getDatabase(context, newProfileId)
        val defaultHistory = history()
        val defaultSet = setHistory(defaultHistory)
        defaultDatabase!!.workoutHistoryDao().insert(defaultHistory)
        defaultDatabase!!.setHistoryDao().insert(defaultSet)
        val defaultHistoryIdsBeforeTargetWrite =
            defaultDatabase!!.workoutHistoryDao().getAllWorkoutHistories().map { it.id }.toSet()
        val defaultSetIdsBeforeTargetWrite = defaultDatabase!!.setHistoryDao().getAllSetHistories().map { it.id }.toSet()

        val importedHistory = history()
        val importedSet = setHistory(importedHistory)
        targetDatabase!!.workoutHistoryDao().insert(importedHistory)
        targetDatabase!!.setHistoryDao().insert(importedSet)

        assertEquals(importedHistory, targetDatabase!!.workoutHistoryDao().getWorkoutHistoryById(importedHistory.id))
        assertEquals(importedSet, targetDatabase!!.setHistoryDao().getSetHistoryById(importedSet.id))
        assertNull(defaultDatabase!!.workoutHistoryDao().getWorkoutHistoryById(importedHistory.id))
        assertEquals(
            defaultHistoryIdsBeforeTargetWrite,
            defaultDatabase!!.workoutHistoryDao().getAllWorkoutHistories().map { it.id }.toSet(),
        )
        assertEquals(
            defaultSetIdsBeforeTargetWrite,
            defaultDatabase!!.setHistoryDao().getAllSetHistories().map { it.id }.toSet(),
        )
        assertTrue(Profiles.profiles(context).any { it.id == newProfileId })
        assertFalse(Profiles.profiles(context).single { it.id == activeProfileId }.name == "Jennifer")
    }

    @Test
    fun invalidUnknownTargetRejectsWithoutFallbackOrProfileCreation() {
        val activeProfileId = Profiles.activeProfileId(context)
        val beforeProfileIds = Profiles.profiles(context).map { it.id }.toSet()

        assertNull(
            Profiles.ensureIncomingBackupProfile(
                context,
                payloadProfileId = "../default",
                payloadProfileName = "Jennifer",
            ),
        )
        val validUnknownId = UUID.randomUUID().toString()
        assertNull(Profiles.ensureIncomingBackupProfile(context, validUnknownId, payloadProfileName = null))
        assertEquals(activeProfileId, Profiles.activeProfileId(context))
        assertEquals(beforeProfileIds, Profiles.profiles(context).map { it.id }.toSet())
        assertEquals(activeProfileId, Profiles.ensureIncomingBackupProfile(context, null, null))
    }

    private fun history() = WorkoutHistory(
        id = UUID.randomUUID(),
        workoutId = UUID.randomUUID(),
        date = LocalDate.of(2026, 11, 16),
        time = LocalTime.NOON,
        startTime = LocalDateTime.of(2026, 11, 16, 12, 0),
        duration = 3_600,
        heartBeatRecords = emptyList(),
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = UUID.randomUUID(),
    )

    private fun setHistory(history: WorkoutHistory) = SetHistory(
        id = UUID.randomUUID(),
        workoutHistoryId = history.id,
        exerciseId = UUID.randomUUID(),
        setId = UUID.randomUUID(),
        order = 0u,
        startTime = null,
        endTime = null,
        setData = WeightSetData(actualReps = 8, actualWeight = 20.0, volume = 160.0),
        skipped = false,
    )
}
