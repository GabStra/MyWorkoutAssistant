package com.gabstra.myworkoutassistant.shared

import android.content.Context
import com.gabstra.myworkoutassistant.shared.profile.Profiles
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.util.UUID

/**
 * Makes every plan's [WorkoutPlan.workoutIds] match the workouts that explicitly reference it.
 *
 * This is the authoritative in-memory view used after explicit mutations such as moving workouts
 * to a plan, moving them to "No plan", deleting workouts or deleting a plan. It deliberately does
 * not backfill from plan-side membership: a stale plan list must never reattach a workout that the
 * user explicitly detached.
 *
 * Repository load/save migration does not use this authoritative rewrite. It calls
 * [convertUnassignedPlansToUngroupedWorkouts] with `repairPlanOnlyMembership = true`, which keeps
 * historical one-sided membership instead of erasing it (except contradictory claims to a
 * workout whose explicit owner is a legacy sentinel). Plan membership remains optional: null and
 * unknown [Workout.workoutPlanId] values are preserved here, and empty plans are kept because
 * users may create them before adding workouts.
 */
fun WorkoutStore.synchronizeWorkoutPlanMemberships(): WorkoutStore {
    val workoutIdsByPlanId = workouts
        .mapNotNull { workout -> workout.workoutPlanId?.let { planId -> planId to workout.id } }
        .groupBy({ it.first }, { it.second })
    val synchronizedPlans = workoutPlans.map { plan ->
        val memberIds = workoutIdsByPlanId[plan.id].orEmpty()
        if (plan.workoutIds == memberIds) plan else plan.copy(workoutIds = memberIds)
    }
    return if (synchronizedPlans == workoutPlans) {
        this
    } else {
        copy(workoutPlans = synchronizedPlans)
    }
}

/**
 * Converts every plan named exactly "Unassigned" into ungrouped workouts.
 *
 * The legacy sentinel plan is retired: each workout that still references such a plan is detached
 * by clearing its [Workout.workoutPlanId], and every sentinel plan is removed. Workouts (including
 * their names, order, global IDs and history linkage), all other plans and every other field are
 * preserved. Multiple sentinel plans are all dissolved, and calling this on an already migrated
 * store returns an equal store, so load/save/restore can apply it unconditionally.
 *
 * Plans whose names merely resemble "Unassigned" are left untouched. No placeholder plan is ever
 * created; ungrouped workouts are represented only by a null [Workout.workoutPlanId].
 *
 * @param repairPlanOnlyMembership when true, performs the conservative repository reconciliation:
 * valid explicit non-placeholder plan IDs win, explicit ownership by a reserved placeholder becomes
 * ungrouped even when a real plan also claims the workout, null/unknown IDs are backfilled only
 * when exactly one existing real plan claims the workout, and a claim held only by a reserved
 * placeholder becomes ungrouped. Plan-side claims that contradict an explicitly detached
 * placeholder owner are removed from surviving plans so a later migration cannot reattach the
 * workout; the original conflict remains in the pre-migration recovery snapshot. Other ambiguous
 * claims and references to missing workouts are preserved as-is instead of being silently erased.
 * When false (the default), the store is normalized authoritatively from the workouts, which is
 * what explicit detach/delete operations require.
 */
fun WorkoutStore.convertUnassignedPlansToUngroupedWorkouts(
    repairPlanOnlyMembership: Boolean = false,
): WorkoutStore {
    val sentinelPlanIds = workoutPlans
        .asSequence()
        .filter { isReservedWorkoutPlanName(it.name) }
        .mapTo(mutableSetOf<UUID>()) { it.id }
    if (repairPlanOnlyMembership) {
        return repairPlanMemberships(sentinelPlanIds)
    }
    if (sentinelPlanIds.isEmpty()) {
        return synchronizeWorkoutPlanMemberships()
    }
    val detachedWorkouts = workouts.map { workout ->
        val planId = workout.workoutPlanId
        if (planId != null && planId in sentinelPlanIds) {
            workout.copy(workoutPlanId = null)
        } else {
            workout
        }
    }
    val remainingPlans = workoutPlans.filterNot { it.id in sentinelPlanIds }
    return copy(workouts = detachedWorkouts, workoutPlans = remainingPlans)
        .synchronizeWorkoutPlanMemberships()
}

/**
 * Conservative membership reconciliation for persisted stores.
 *
 * The rules are intentionally deterministic and non-destructive:
 * - A valid explicit non-placeholder [Workout.workoutPlanId] always wins and is ensured present in
 *   that plan.
 * - Explicit ownership by an exact "Unassigned" placeholder becomes null, even when a real plan
 *   also lists the workout. Contradictory plan-side claims for that workout are removed from
 *   surviving plans; otherwise the next migration would treat the stale claim as a plan-only
 *   membership and reattach it. The pre-migration recovery snapshot keeps the original evidence.
 * - A null/unknown ID is backfilled only when exactly one real plan lists the workout. Multiple
 *   real claims are ambiguous and leave the workout ID untouched.
 * - A workout whose only claim is an exact "Unassigned" placeholder becomes ungrouped.
 * - Existing plan member IDs are otherwise preserved in order, including duplicate entries and
 *   references to workouts absent from this store (for example a partial backup). They are
 *   visible evidence rather than silent data loss.
 * - Exact-name placeholder plans are removed along with their now-unreachable list.
 */
private fun WorkoutStore.repairPlanMemberships(sentinelPlanIds: Set<UUID>): WorkoutStore {
    val realPlanIds = workoutPlans
        .asSequence()
        .filterNot { it.id in sentinelPlanIds }
        .mapTo(LinkedHashSet()) { it.id }
    val claimingPlanIdsByWorkoutId = LinkedHashMap<UUID, LinkedHashSet<UUID>>()
    workoutPlans.forEach { plan ->
        plan.workoutIds.forEach { workoutId ->
            claimingPlanIdsByWorkoutId
                .getOrPut(workoutId) { LinkedHashSet() }
                .add(plan.id)
        }
    }

    val backfilledWorkoutIdsByPlanId = LinkedHashMap<UUID, MutableList<UUID>>()
    val sentinelDetachedWorkoutIds = LinkedHashSet<UUID>()
    val repairedWorkouts = workouts.map { workout ->
        val currentPlanId = workout.workoutPlanId
        if (currentPlanId != null && currentPlanId in realPlanIds) {
            backfilledWorkoutIdsByPlanId
                .getOrPut(currentPlanId) { mutableListOf() }
                .add(workout.id)
            return@map workout
        }

        val claimingPlanIds = claimingPlanIdsByWorkoutId[workout.id].orEmpty()
        val realClaims = claimingPlanIds.filter { it in realPlanIds }
        val explicitSentinelOwnership =
            currentPlanId != null && currentPlanId in sentinelPlanIds
        val sentinelOnlyClaims = claimingPlanIds.isNotEmpty() &&
            claimingPlanIds.all { it in sentinelPlanIds }
        val detachedFromSentinel = explicitSentinelOwnership || sentinelOnlyClaims
        val repairedPlanId = when {
            detachedFromSentinel -> null
            realClaims.size == 1 -> realClaims.single()
            else -> currentPlanId
        }
        if (detachedFromSentinel) {
            sentinelDetachedWorkoutIds.add(workout.id)
        }
        if (repairedPlanId != null) {
            backfilledWorkoutIdsByPlanId
                .getOrPut(repairedPlanId) { mutableListOf() }
                .add(workout.id)
        }
        if (repairedPlanId == currentPlanId) workout
        else workout.copy(workoutPlanId = repairedPlanId)
    }

    val repairedPlans = workoutPlans
        .filterNot { it.id in sentinelPlanIds }
        .map { plan ->
            val backfilledIds = backfilledWorkoutIdsByPlanId[plan.id].orEmpty()
            val retainedIds = if (sentinelDetachedWorkoutIds.isEmpty()) {
                plan.workoutIds
            } else {
                plan.workoutIds.filterNot { it in sentinelDetachedWorkoutIds }
            }
            val existingIds = retainedIds.toSet()
            val missingIds = backfilledIds.filterNot { it in existingIds }
            val repairedIds = if (missingIds.isEmpty()) retainedIds else retainedIds + missingIds
            if (repairedIds == plan.workoutIds) plan else plan.copy(workoutIds = repairedIds)
        }

    return if (repairedWorkouts == workouts && repairedPlans == workoutPlans) {
        this
    } else {
        copy(workouts = repairedWorkouts, workoutPlans = repairedPlans)
    }
}

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
        // Workout plan membership is optional. Legacy "Unassigned" plans are dissolved into
        // ungrouped workouts, then one-sided historical membership is reconciled conservatively:
        // a unique plan-side claim is backfilled, while other ambiguous/conflicting/missing
        // references are retained instead of being erased. The exception is a stale real-plan
        // claim that contradicts explicit sentinel ownership; it must be removed or the next
        // migration would reattach the workout. Never invent or assign a sentinel plan.
        return workoutStore.convertUnassignedPlansToUngroupedWorkouts(
            repairPlanOnlyMembership = true,
        )
    }

    override fun saveWorkoutStore(workoutStore: WorkoutStore) {
        // Dissolve legacy "Unassigned" plans and normalize derived membership before saving;
        // null and unknown plan IDs are valid.
        persist(migrateWorkoutStore(workoutStore))
    }

    override fun saveWorkoutStoreFromJson(workoutStoreJson: String) {
        persist(migrateWorkoutStore(fromJSONToWorkoutStore(workoutStoreJson)))
    }

    /**
     * Writes only the shared half of a store.
     *
     * Full-backup restore uses this once for the union shared library instead of letting every
     * profile save a profile-filtered copy over it.
     */
    fun saveSharedContent(workoutStore: WorkoutStore) {
        writeStore(
            File(sharedFilesDir, FILENAME),
            migrateWorkoutStore(workoutStore).sharedContentOnly(),
        )
    }

    /**
     * Writes only one profile's personal half, leaving the shared file untouched.
     *
     * Only meaningful for a split store: a non-split store cannot persist personal settings
     * without also replacing the shared content, which would drop other profiles' workouts.
     */
    fun savePersonalSettings(workoutStore: WorkoutStore) {
        check(isSplit) {
            "Personal settings must be saved through a split profile store; shared content " +
                "must not be rewritten per profile."
        }
        writeStore(
            File(filesDir, FILENAME),
            migrateWorkoutStore(workoutStore).personalSettingsOnly(),
        )
    }

    private fun persist(workoutStore: WorkoutStore) {
        if (!isSplit) {
            writeStore(File(filesDir, FILENAME), workoutStore)
            return
        }
        writeStore(File(sharedFilesDir, FILENAME), workoutStore.sharedContentOnly())
        writeStore(File(filesDir, FILENAME), workoutStore.personalSettingsOnly())
    }

    /**
     * Reads one store file and persists any migration it applies. Null when absent or unreadable.
     *
     * Migration is not limited to legacy schema versions: an already-current file can still carry
     * a legacy "Unassigned" plan, and leaving that only in memory would expose the sentinel to
     * direct file readers such as the full-backup exporter.
     */
    private fun readStore(file: File): WorkoutStore? {
        if (!file.exists()) return null
        val jsonString = try {
            file.readText()
        } catch (_: Exception) {
            return null
        }
        val workoutStore = try {
            fromJSONToWorkoutStore(jsonString)
        } catch (_: Exception) {
            return null
        }
        val migrated = migrateWorkoutStore(workoutStore)
        val legacySchema = !jsonString.contains("\"schemaVersion\"") ||
            Regex("\"schemaVersion\"\\s*:\\s*1(?:\\D|$)").containsMatchIn(jsonString)
        if (migrated != workoutStore || legacySchema) {
            persistMigration(file, migrated)
        }
        return migrated
    }

    /**
     * Keeps the pre-migration file once, then atomically replaces it with [migrated].
     *
     * A failed recovery copy or write must not make an otherwise readable store look absent, so
     * the migrated value stays available in memory and the next successful save retries the write.
     */
    private fun persistMigration(file: File, migrated: WorkoutStore) {
        try {
            val recoveryFile = File(file.parentFile, "${file.name}.pre-migration-recovery")
            if (!recoveryFile.exists()) {
                file.copyTo(recoveryFile, overwrite = false)
            }
            writeStore(file, migrated)
        } catch (_: Exception) {
            // Keep serving the migrated store in memory; atomic write leaves the original intact.
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
