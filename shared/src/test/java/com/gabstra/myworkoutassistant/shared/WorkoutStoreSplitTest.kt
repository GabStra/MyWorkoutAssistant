package com.gabstra.myworkoutassistant.shared

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutStoreSplitTest {

    private lateinit var context: Context
    private lateinit var profileDirectory: File
    private lateinit var repository: WorkoutStoreRepository

    @Before
    fun setUp() {
        context = ApplicationProvider.getApplicationContext()
        profileDirectory = File(context.filesDir, "profiles/alice")
        repository = WorkoutStoreRepository(profileDirectory, context.filesDir)
    }

    @Test
    fun sharedContentAndPersonalSettingsArePersistedToSeparateFiles() {
        val plan = WorkoutPlan(id = UUID.randomUUID(), name = "Push", workoutIds = emptyList(), order = 0)
        repository.saveWorkoutStore(
            WorkoutStore(
                workouts = emptyList(),
                equipments = emptyList(),
                accessoryEquipments = emptyList(),
                workoutPlans = listOf(plan),
                birthDateYear = 1990,
                weightKg = 82.5,
                progressionPercentageAmount = 2.0,
            )
        )

        val shared = fromJSONToWorkoutStore(File(context.filesDir, "workout_store.json").readText())
        assertEquals(listOf(plan), shared.workoutPlans)
        assertEquals(0L, shared.birthDateYear.toLong())
        assertEquals(0.0, shared.weightKg, 0.0)

        val personal = fromJSONToWorkoutStore(File(profileDirectory, "workout_store.json").readText())
        assertTrue(personal.workoutPlans.isEmpty())
        assertEquals(1990, personal.birthDateYear)
        assertEquals(82.5, personal.weightKg, 0.0)

        val merged = repository.getWorkoutStore()
        assertEquals(listOf(plan), merged.workoutPlans)
        assertEquals(1990, merged.birthDateYear)
        assertEquals(82.5, merged.weightKg, 0.0)
    }

    @Test
    fun oneProfileDoesNotSeeAnotherProfilesMetrics() {
        val alice = WorkoutStoreRepository(File(context.filesDir, "profiles/alice"), context.filesDir)
        val bob = WorkoutStoreRepository(File(context.filesDir, "profiles/bob"), context.filesDir)

        alice.saveWorkoutStore(baseStore().copy(weightKg = 60.0, birthDateYear = 1995))
        bob.saveWorkoutStore(baseStore().copy(weightKg = 82.5, birthDateYear = 1990))

        assertEquals(60.0, alice.getWorkoutStore().weightKg, 0.0)
        assertEquals(82.5, bob.getWorkoutStore().weightKg, 0.0)
        assertEquals(1995, alice.getWorkoutStore().birthDateYear)
        assertEquals(1990, bob.getWorkoutStore().birthDateYear)
    }

    private fun baseStore() = WorkoutStore(
        workouts = emptyList(),
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        birthDateYear = 0,
        weightKg = 0.0,
        progressionPercentageAmount = 0.0,
    )

    @Test
    fun appBackupKeepsItsProfileIdAcrossJson() {
        val backup = AppBackup(
            baseStore(),
            emptyList(),
            emptyList(),
            emptyList(),
            emptyList(),
            emptyList(),
            emptyList(),
            ProfileId = "bob",
            ProfileName = "Bob",
        )

        val roundTripped = fromJSONtoAppBackup(fromAppBackupToJSON(backup))

        assertEquals("bob", roundTripped.ProfileId)
        // The name is what makes the backup restorable after a reinstall.
        assertEquals("Bob", roundTripped.ProfileName)
    }

    @Test
    fun backupWithoutAProfileIdStaysCompatible() {
        val legacyJson = fromAppBackupToJSON(
            AppBackup(
                baseStore(),
                emptyList(),
                emptyList(),
                emptyList(),
                emptyList(),
                emptyList(),
                emptyList(),
            )
        )

        assertEquals(null, fromJSONtoAppBackup(legacyJson).ProfileId)
    }

    @Test
    fun whichPlansTheWatchOffersIsPerProfileAndNeverShared() {
        val alice = WorkoutStoreRepository(File(context.filesDir, "profiles/alice"), context.filesDir)
        val bob = WorkoutStoreRepository(File(context.filesDir, "profiles/bob"), context.filesDir)
        val planId = UUID.randomUUID()

        alice.saveWorkoutStore(baseStore().copy(visibleWorkoutPlanIds = listOf(planId)))
        bob.saveWorkoutStore(baseStore())

        assertEquals(listOf(planId), alice.getWorkoutStore().visibleWorkoutPlanIds)
        assertNull(bob.getWorkoutStore().visibleWorkoutPlanIds)

        // The shared file must not carry one profile's selection.
        val shared = fromJSONToWorkoutStore(File(context.filesDir, "workout_store.json").readText())
        assertNull(shared.visibleWorkoutPlanIds)
    }

    @Test
    fun fullBackupCarriesEveryProfileThroughJson() {
        val personalStore = baseStore().copy(weightKg = 70.0, birthDateYear = 1990)
        val fullBackup = FullBackup(
            createdAtEpochMs = 1L,
            sharedStore = baseStore(),
            activeProfileId = "p1",
            profiles = listOf(
                ProfileBackup(
                    profileId = "p1",
                    profileName = "Alice",
                    backup = AppBackup(
                        personalStore,
                        emptyList(),
                        emptyList(),
                        emptyList(),
                        emptyList(),
                        emptyList(),
                        emptyList(),
                        ProfileId = "p1",
                        ProfileName = "Alice",
                    ),
                ),
            ),
            settings = FullBackupSettings(mobileLlmEnabled = true, healthConnectProfileId = "p1"),
            motionCaptureFiles = listOf(
                MotionCaptureFileBackup("motion_capture/sessions/a/events.csv", "H4sIAAAA"),
            ),
        )

        val roundTripped = fromJSONToFullBackup(fromFullBackupToJSON(fullBackup))

        assertEquals("p1", roundTripped.activeProfileId)
        assertEquals(1, roundTripped.profiles.size)
        assertEquals("Alice", roundTripped.profiles[0].profileName)
        // The nested AppBackup must survive the envelope, not just the top-level fields.
        assertEquals(70.0, roundTripped.profiles[0].backup.WorkoutStore.weightKg, 0.0)
        assertEquals("p1", roundTripped.profiles[0].backup.ProfileId)
        assertEquals("p1", roundTripped.settings?.healthConnectProfileId)
        assertEquals(1, roundTripped.motionCaptureFiles.size)
        assertEquals(
            "motion_capture/sessions/a/events.csv",
            roundTripped.motionCaptureFiles[0].relativePath,
        )
    }
}
