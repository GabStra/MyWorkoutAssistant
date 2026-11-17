package com.gabstra.myworkoutassistant.shared

import android.content.Context
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

/**
 * Reads and writes [WorkoutStore].
 *
 * When [sharedFilesDir] differs from [filesDir] the store is split: shared content (library,
 * workouts, equipment, plans) lives in the shared file and everything personal to one profile
 * lives in the profile's own file. Callers keep seeing a single merged object.
 */
class WorkoutStoreRepository(
    private val filesDir: File,
    private val sharedFilesDir: File = filesDir,
) : IWorkoutStoreRepository {

    companion object {
        private const val FILENAME = "workout_store.json"

        fun forActiveProfile(context: Context): WorkoutStoreRepository {
            val app = context.applicationContext
            return WorkoutStoreRepository(Profiles.activeDirectory(app), app.filesDir)
        }
    }

    private val isSplit: Boolean
        get() = filesDir.absolutePath != sharedFilesDir.absolutePath

    override fun getWorkoutStore(): WorkoutStore {
        if (!isSplit) {
            return migrateWorkoutStore(readStore(File(filesDir, FILENAME)) ?: emptyWorkoutStore())
        }
        val shared = readStore(File(sharedFilesDir, FILENAME)) ?: emptyWorkoutStore()
        val personal = readStore(File(filesDir, FILENAME)) ?: emptyWorkoutStore()
        return migrateWorkoutStore(shared.mergedWithPersonalSettingsOf(personal))
    }

    fun migrateWorkoutStore(workoutStore: WorkoutStore): WorkoutStore {
        val workoutPlans = workoutStore.workoutPlans
        val workouts = workoutStore.workouts

        // If workoutPlans is empty, create default "Unassigned" plan and assign all workouts to it
        if (workoutPlans.isEmpty() && workouts.isNotEmpty()) {
            val unassignedPlanId = UUID.randomUUID()
            val unassignedPlan = WorkoutPlan(
                id = unassignedPlanId,
                name = UNASSIGNED_PLAN_NAME,
                workoutIds = workouts.map { it.id },
                order = 0
            )

            // Update all workouts to have the workoutPlanId
            val migratedWorkouts = workouts.map { workout ->
                if (workout.workoutPlanId == null) {
                    workout.copy(workoutPlanId = unassignedPlanId)
                } else {
                    workout
                }
            }

            return workoutStore.copy(
                workouts = migratedWorkouts,
                workoutPlans = listOf(unassignedPlan)
            )
        }

        // If workouts exist but some don't have workoutPlanId, assign them to Unassigned plan
        val workoutsWithoutPlan = workouts.filter { it.workoutPlanId == null }
        if (workoutsWithoutPlan.isNotEmpty()) {
            val unassignedPlan = workoutPlans.find { it.name == UNASSIGNED_PLAN_NAME }
            val unassignedPlanId = unassignedPlan?.id ?: UUID.randomUUID()

            val updatedPlans = if (unassignedPlan == null) {
                val newUnassignedPlan = WorkoutPlan(
                    id = unassignedPlanId,
                    name = UNASSIGNED_PLAN_NAME,
                    workoutIds = workoutsWithoutPlan.map { it.id },
                    order = (workoutPlans.maxOfOrNull { it.order } ?: -1) + 1
                )
                workoutPlans + newUnassignedPlan
            } else {
                workoutPlans.map { plan ->
                    if (plan.id == unassignedPlanId) {
                        plan.copy(workoutIds = plan.workoutIds + workoutsWithoutPlan.map { it.id })
                    } else {
                        plan
                    }
                }
            }

            val migratedWorkouts = workouts.map { workout ->
                if (workout.workoutPlanId == null) {
                    workout.copy(workoutPlanId = unassignedPlanId)
                } else {
                    workout
                }
            }

            return workoutStore.copy(
                workouts = migratedWorkouts,
                workoutPlans = updatedPlans
            )
        }

        return workoutStore
    }

    override fun saveWorkoutStore(workoutStore: WorkoutStore) {
        // Migrate the workout store before saving to ensure it's in a valid state
        // (e.g., create "Unassigned" plan for workouts without a plan)
        persist(migrateWorkoutStore(workoutStore))
    }

    override fun saveWorkoutStoreFromJson(workoutStoreJson: String) {
        persist(fromJSONToWorkoutStore(workoutStoreJson))
    }

    private fun persist(workoutStore: WorkoutStore) {
        if (!isSplit) {
            writeStore(File(filesDir, FILENAME), workoutStore)
            return
        }
        writeStore(File(sharedFilesDir, FILENAME), workoutStore.sharedContentOnly())
        writeStore(File(filesDir, FILENAME), workoutStore.personalSettingsOnly())
    }

    /** Reads one store file, upgrading the legacy schema in place. Null when absent or unreadable. */
    private fun readStore(file: File): WorkoutStore? {
        if (!file.exists()) return null
        return try {
            val jsonString = file.readText()
            val workoutStore = fromJSONToWorkoutStore(jsonString)
            val legacySchema = !jsonString.contains("\"schemaVersion\"") ||
                Regex("\"schemaVersion\"\\s*:\\s*1(?:\\D|$)").containsMatchIn(jsonString)
            if (legacySchema) {
                val recoveryFile = File(file.parentFile, "$FILENAME.v1-recovery")
                if (!recoveryFile.exists()) file.copyTo(recoveryFile, overwrite = false)
                writeStore(file, workoutStore)
            }
            workoutStore
        } catch (_: Exception) {
            null
        }
    }

    private fun writeStore(file: File, workoutStore: WorkoutStore) {
        writeAtomically(file, fromWorkoutStoreToJSON(workoutStore))
    }

    private fun emptyWorkoutStore() = WorkoutStore(
        workouts = emptyList(),
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        birthDateYear = 0,
        weightKg = 0.0,
        progressionPercentageAmount = 0.0
    )

    private fun writeAtomically(destination: File, contents: String) {
        destination.parentFile?.mkdirs()
        val temporary = File(destination.parentFile, "${destination.name}.tmp")
        temporary.writeText(contents)
        try {
            Files.move(
                temporary.toPath(), destination.toPath(),
                StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE,
            )
        } catch (_: Exception) {
            Files.move(
                temporary.toPath(), destination.toPath(), StandardCopyOption.REPLACE_EXISTING,
            )
        }
    }
}
