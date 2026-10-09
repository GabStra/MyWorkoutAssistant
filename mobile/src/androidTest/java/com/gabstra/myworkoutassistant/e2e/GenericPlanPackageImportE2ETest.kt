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
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.sync.MobileSyncToWatchWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID

/**
 * Proves the phone import path is workout-type agnostic: a generated NON-WOD
 * plan package (a standard-style strength & engine session produced through the
 * same wod_importer_pkg pipeline) flows through the app's real import path —
 * parse, definition merge, movement payload checks, store save — then drives
 * the real phone -> Wear sync worker and waits for it to succeed.
 *
 * Also asserts the CrossFit-mode fields survive the import: the AMRAP superset
 * (amrap=true + time cap + one work set per member) and goal-based open-ended
 * cardio sets (autoStop=false + targetDistanceMeters).
 */
@RunWith(AndroidJUnit4::class)
class GenericPlanPackageImportE2ETest {

    private val workoutName = "Strength & Engine B"

    private fun loadPackageJson(): String =
        InstrumentationRegistry.getInstrumentation()
            .context.assets.open("generated_plan_package.json").bufferedReader().use { it.readText() }

    @Test
    fun genericPlanPackage_importsIntoStoreAndSyncsToWear() = runBlocking {
        val context = ApplicationProvider.getApplicationContext<android.content.Context>()

        // Known clean base, same as the WOD import test.
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
        val genericWorkout = savedStore.workouts.singleOrNull { it.name == workoutName }
        assertNotNull("generic workout missing from the imported store", genericWorkout)

        val exercisesByName = genericWorkout!!.workoutComponents.flatMap { component ->
            when (component) {
                is Exercise -> listOf(component)
                is Superset -> component.exercises
                else -> emptyList()
            }
        }.associateBy { it.name }

        listOf(
            "Barbell Back Squat", "Weighted Pull-Up", "Row", "Dumbbell Bench Press",
            "Weighted Burpee", "Weighted Lunge", "Bike Erg Seated",
        ).forEach { name ->
            assertTrue("movement '$name' missing from imported generic workout", name in exercisesByName)
        }

        // The AMRAP block must carry the new mode end-to-end through the import.
        val amrapSupersets = componentsOf(genericWorkout.workoutComponents).filterIsInstance<Superset>()
            .filter { it.amrap }
        assertTrue("expected exactly one amrap superset", amrapSupersets.size == 1)
        val amrap = amrapSupersets.single()
        assertTrue("amrap superset must carry its time cap", (amrap.timeCapSeconds ?: 0) == 600)
        assertTrue(
            "amrap members must define exactly one work set each",
            amrap.exercises.all { exercise -> workSets(exercise.sets).size == 1 }
        )

        // Goal-based cardio sets must be open-ended (autoStop=false) with the target.
        val rowGoals = workSets(exercisesByName.getValue("Row").sets)
            .filterIsInstance<EnduranceSet>()
            .mapNotNull { it.targetDistanceMeters }
        assertTrue("row sets must carry the 500m goal", rowGoals.isNotEmpty() && rowGoals.all { it == 500.0 })
        assertTrue(
            "goal-based row sets must not auto-stop",
            workSets(exercisesByName.getValue("Row").sets).filterIsInstance<EnduranceSet>().none { it.autoStop }
        )

        // --- real phone -> Wear sync ---
        val request = OneTimeWorkRequestBuilder<MobileSyncToWatchWorker>().build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            "mobile_sync_to_watch",
            ExistingWorkPolicy.REPLACE,
            request
        )
        waitForSyncWorkerSuccess(context, request.id, timeoutMs = 90_000)
    }

    private fun componentsOf(components: List<com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent>) =
        components

    private fun workSets(sets: List<Set>): List<Set> = sets.filterNot { it is RestSet }

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
            if (info?.state == WorkInfo.State.FAILED || info?.state == WorkInfo.State.CANCELLED) {
                error("MobileSyncToWatchWorker ended in $lastState")
            }
            delay(500)
        }
        error("MobileSyncToWatchWorker did not succeed within ${timeoutMs}ms (last state: $lastState)")
    }
}
