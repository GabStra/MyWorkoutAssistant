package com.gabstra.myworkoutassistant.e2e

import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkInfo
import androidx.work.WorkManager
import com.gabstra.myworkoutassistant.e2e.fixtures.CrossDeviceSyncPhoneWorkoutStoreFixture
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.effectiveFamilyId
import com.gabstra.myworkoutassistant.shared.fromJSONToWorkoutPlanPackage
import com.gabstra.myworkoutassistant.shared.motion.requireExerciseMovementPayloads
import com.gabstra.myworkoutassistant.shared.motion.restoreExerciseMovementBackups
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/**
 * Phone phase of the WOD importer e2e: takes the generated WOD plan package
 * (produced by wod_importer_pkg from the gym's published WOD text) through the
 * app's real import path — parse, definition merge with conflict detection,
 * movement payload checks, store save — then drives the real phone -> Wear
 * sync worker and waits for it to succeed.
 *
 * The wear phase (WodWorkoutVisibilityE2ETest) verifies the workout arrives on
 * the watch and is selectable.
 */
@RunWith(AndroidJUnit4::class)
class WodPackageImportE2ETest {

    private val workoutName = "WOD 2026-10-06 HYROX-PREP"

    private fun loadPackageJson(): String =
        InstrumentationRegistry.getInstrumentation()
            .context.assets.open("wod_2026-10-06.json").bufferedReader().use { it.readText() }

    @Test
    fun wodPackage_importsIntoStoreAndSyncsToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        // Known clean base: the cross-device fixture store (its movement payload is
        // written below), so the import merge has deterministic starting state.
        val db = AppDatabase.getDatabase(context)
        db.workoutHistoryDao().deleteAll()
        db.setHistoryDao().deleteAll()
        db.workoutRecordDao().deleteAll()
        db.exerciseInfoDao().deleteAll()
        db.exerciseSessionProgressionDao().deleteAll()

        val repository = WorkoutStoreRepository(context.filesDir)
        val baseStore = CrossDeviceSyncPhoneWorkoutStoreFixture.createWorkoutStore()
        repository.saveWorkoutStore(baseStore)
        com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementStorage.writeMovementJson(
            context = context,
            movementRef = CrossDeviceSyncPhoneWorkoutStoreFixture.movementRef(),
            json = CrossDeviceSyncPhoneWorkoutStoreFixture.MOVEMENT_JSON.trimIndent()
        )

        // --- the app's real import path (mirrors MainActivity's plan-package flow) ---
        val packageJson = loadPackageJson()
        val imported = fromJSONToWorkoutPlanPackage(packageJson)
        assertTrue(imported.name.isNotBlank())
        assertTrue(imported.workouts.isNotEmpty())

        val newPlanId = UUID.randomUUID()
        val newPlan = WorkoutPlan(
            id = newPlanId,
            name = imported.name,
            workoutIds = imported.workouts.map { it.id },
            order = 0
        )
        val workoutsWithPlanId = imported.workouts.map { it.copy(workoutPlanId = newPlanId) }
        val currentStore = repository.getWorkoutStore()
        val importedDefinitions = imported.exerciseDefinitions.map { it.copy(exerciseFamilyId = it.effectiveFamilyId()) }
        val existingById = currentStore.exerciseDefinitions.associateBy { it.id }
        importedDefinitions.forEach { definition ->
            val existing = existingById[definition.id]
            require(existing == null || existing == definition) {
                "Exercise definition ${definition.id} conflicts with an existing library entry."
            }
        }
        val mergedStore = currentStore.copy(
            workouts = workoutsWithPlanId,
            exerciseDefinitions = (currentStore.exerciseDefinitions + importedDefinitions).distinctBy { it.id },
            equipments = imported.equipments,
            accessoryEquipments = imported.accessoryEquipments,
            workoutPlans = listOf(newPlan)
        )
        withContext(Dispatchers.IO) {
            restoreExerciseMovementBackups(context, imported.exerciseMovements)
            requireExerciseMovementPayloads(context, mergedStore)
        }
        repository.saveWorkoutStore(mergedStore)
        // ---------------------------------------------------------------------------

        val savedStore = repository.getWorkoutStore()
        val wodWorkout = savedStore.workouts.singleOrNull { it.name == workoutName }
        assertNotNull("WOD workout missing from the imported store", wodWorkout)

        // The pipeline's encoding varies run-to-run (timed blocks may become
        // standing/seated supersets etc.), so assert semantics — every expected
        // movement must appear somewhere in the workout — not the exact shape.
        val movementNames = wodWorkout!!.workoutComponents.flatMap { component ->
            when (component) {
                is com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise -> listOf(component.name)
                is com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset ->
                    component.exercises.map { it.name }
                else -> emptyList()
            }
        }
        assertTrue("imported WOD has no movement components", movementNames.isNotEmpty())
        listOf("Row", "Bike Erg", "GTOH Plate", "Shuttle Run").forEach { expected ->
            assertTrue(
                "movement '$expected' missing from imported WOD (got: $movementNames)",
                movementNames.any { it.contains(expected, ignoreCase = true) }
            )
        }

        val definitionNames = savedStore.exerciseDefinitions.map { it.name }
        listOf("Row", "Bike Erg Standing", "Bike Erg Seated", "GTOH Plate", "Shuttle Run").forEach { name ->
            assertTrue("definition $name missing after import", name in definitionNames)
        }
        val equipmentNames = savedStore.equipments.map { it.name }
        assertTrue("Rower" in equipmentNames)
        assertTrue("Bike Erg" in equipmentNames)

        // --- real phone -> Wear sync ---
        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "mobile_sync_to_watch",
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, timeoutMs = 90_000)
    }

    private suspend fun waitForSyncWorkerSuccess(context: android.content.Context, requestId: UUID, timeoutMs: Long) {
        val workManager = WorkManager.getInstance(context)
        val deadline = System.currentTimeMillis() + timeoutMs
        var lastState: WorkInfo.State? = null
        while (System.currentTimeMillis() < deadline) {
            val info = workManager.getWorkInfoByIdFlow(requestId).first()
            lastState = info?.state
            if (info?.state == WorkInfo.State.SUCCEEDED) {
                return
            }
            if (info?.state == WorkInfo.State.FAILED) {
                error("MobileSyncToWatchWorker failed")
            }
            kotlinx.coroutines.delay(500)
        }
        error("MobileSyncToWatchWorker did not succeed within ${timeoutMs}ms (last state: $lastState)")
    }
}
