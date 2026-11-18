package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutPlan
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.WorkoutStoreRepository
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import java.nio.file.Files
import java.nio.file.Path
import java.time.LocalDate
import java.util.UUID

class WatchStoreUpdateMergeTest {

    private lateinit var directory: Path

    @Before
    fun setUp() {
        directory = Files.createTempDirectory("watch-store-update-merge")
    }

    @After
    fun tearDown() {
        directory.toFile().deleteRecursively()
    }

    @Test
    fun equipmentUpdatePreservesLocalEntitySetOrderPlansSettingsAndLibraries() {
        val plan = plan("Push")
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val exerciseId = UUID.randomUUID()
        val localWorkout = workout(
            name = "Bench day",
            workoutPlanId = plan.id,
            components = listOf(
                exercise(
                    id = exerciseId,
                    equipmentId = equipmentA.id,
                    sets = listOf(weightSet(weight = 100.0)),
                ),
            ),
        )
        val localOnlyWorkout = workout(name = "Phone-only workout", workoutPlanId = null, order = 1)
        val localStore = store(
            workouts = listOf(localWorkout, localOnlyWorkout),
            plans = listOf(plan.copy(workoutIds = listOf(localWorkout.id, localOnlyWorkout.id))),
            equipments = listOf(equipmentA, equipmentB),
            weightKg = 82.5,
            birthDateYear = 1991,
        )

        val incomingWorkout = localWorkout.copy(
            workoutComponents = listOf(
                exercise(
                    id = exerciseId,
                    equipmentId = equipmentB.id,
                    sets = localWorkout.exercise(exerciseId).sets,
                ),
            ),
        )
        val deletedOnPhone = workout(name = "Deleted on phone", workoutPlanId = null)
        val staleWatchSnapshot = store(
            workouts = listOf(incomingWorkout, deletedOnPhone),
            plans = listOf(plan.copy(name = "Stale watch plan", workoutIds = listOf(localWorkout.id))),
            equipments = listOf(equipmentA),
            weightKg = 60.0,
            birthDateYear = 1970,
        )

        val merged = localStore.mergeWatchWorkoutDefinitionUpdate(staleWatchSnapshot)

        assertEquals(
            listOf(localWorkout.id, localOnlyWorkout.id),
            merged.workouts.map { it.id },
        )
        assertEquals(localStore.workoutPlans, merged.workoutPlans)
        assertEquals(localStore.equipments, merged.equipments)
        assertEquals(82.5, merged.weightKg, 0.0)
        assertEquals(1991, merged.birthDateYear)
        assertEquals(localOnlyWorkout, merged.workout(localOnlyWorkout.id))
        assertEquals(
            equipmentB.id,
            merged.workout(localWorkout.id).exercise(exerciseId).equipmentId,
        )
    }

    @Test
    fun staleWorkoutDefinitionDoesNotOverwriteNewerPhoneEdits() {
        val exerciseId = UUID.randomUUID()
        val localWorkout = workout(
            name = "Renamed on phone",
            description = "Phone description",
            components = listOf(
                exercise(
                    id = exerciseId,
                    name = "Renamed exercise on phone",
                    notes = "Phone notes",
                    sets = listOf(weightSet(reps = 10, weight = 100.0)),
                ),
            ),
        )
        val localStore = store(workouts = listOf(localWorkout), plans = emptyList())
        val staleIncomingWorkout = localWorkout.copy(
            name = "Old workout name",
            description = "",
            workoutComponents = listOf(
                exercise(
                    id = exerciseId,
                    name = "Old exercise name",
                    notes = "",
                    sets = listOf(weightSet(reps = 8, weight = 100.0)),
                ),
            ),
        )

        val merged = localStore.mergeWatchWorkoutDefinitionUpdate(
            store(workouts = listOf(staleIncomingWorkout), plans = emptyList()),
        )

        assertEquals(localWorkout, merged.workout(localWorkout.id))
    }

    @Test
    fun calibrationUpdateAppliesToMatchingActiveVersionAndKeepsIdentityAndVersionChain() {
        val previousVersionId = UUID.randomUUID()
        val nextVersionId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val pendingSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val localExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(id = pendingSetId, weight = 100.0, subCategory = SetSubCategory.CalibrationPendingSet),
                weightSet(id = workSetId, weight = 100.0, subCategory = SetSubCategory.WorkSet),
            ),
        )
        val localWorkout = workout(
            name = "Calibrated on watch",
            workoutPlanId = UUID.randomUUID(),
            components = listOf(localExercise),
        ).copy(
            previousVersionId = previousVersionId,
            nextVersionId = nextVersionId,
            globalId = UUID.randomUUID(),
        )
        val localStore = store(workouts = listOf(localWorkout), plans = emptyList())
        val incomingWorkout = localWorkout.copy(
            name = "Stale phone name",
            description = "Stale snapshot",
            order = 99,
            previousVersionId = null,
            nextVersionId = null,
            isActive = true,
            workoutComponents = listOf(
                localExercise.copy(
                    requiresLoadCalibration = false,
                    sets = listOf(
                        weightSet(id = pendingSetId, weight = 90.0, subCategory = SetSubCategory.WorkSet),
                        weightSet(id = workSetId, weight = 90.0, subCategory = SetSubCategory.WorkSet),
                    ),
                ),
            ),
        )

        val merged = localStore.mergeWatchWorkoutDefinitionUpdate(
            store(workouts = listOf(incomingWorkout), plans = emptyList()),
        )
        val mergedWorkout = merged.workout(localWorkout.id)
        val mergedExercise = mergedWorkout.exercise(exerciseId)

        assertEquals(localWorkout.name, mergedWorkout.name)
        assertEquals(localWorkout.description, mergedWorkout.description)
        assertEquals(localWorkout.order, mergedWorkout.order)
        assertEquals(localWorkout.workoutPlanId, mergedWorkout.workoutPlanId)
        assertEquals(previousVersionId, mergedWorkout.previousVersionId)
        assertEquals(nextVersionId, mergedWorkout.nextVersionId)
        assertEquals(localWorkout.globalId, mergedWorkout.globalId)
        assertFalse(mergedExercise.requiresLoadCalibration)
        assertEquals(listOf(90.0, 90.0), mergedExercise.sets.map { (it as WeightSet).weight })
        assertEquals(listOf(8, 8), mergedExercise.sets.map { (it as WeightSet).reps })
    }

    @Test
    fun calibrationShapedSnapshotThatChangesOtherSetFieldsIsIgnored() {
        val exerciseId = UUID.randomUUID()
        val localExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    reps = 8,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val localWorkout = workout("Calibration target", components = listOf(localExercise))
        val localStore = store(workouts = listOf(localWorkout), plans = emptyList())
        val staleIncomingWorkout = localWorkout.copy(
            workoutComponents = listOf(
                localExercise.copy(
                    requiresLoadCalibration = false,
                    sets = listOf(
                        weightSet(
                            reps = 10,
                            weight = 90.0,
                            subCategory = SetSubCategory.WorkSet,
                        ),
                    ),
                ),
            ),
        )

        val merged = localStore.mergeWatchWorkoutDefinitionUpdate(
            store(workouts = listOf(staleIncomingWorkout), plans = emptyList()),
        )

        assertEquals(localWorkout, merged.workout(localWorkout.id))
    }

    @Test
    fun incomingOnlyAndInactiveObsoleteWorkoutsAreNotResurrected() {
        val activeWorkout = workout("Active")
        val inactiveWorkout = workout("Old version").copy(
            isActive = false,
            nextVersionId = activeWorkout.id,
        )
        val incomingOnlyDeletedWorkout = workout("Deleted on phone")
        val localStore = store(
            workouts = listOf(activeWorkout, inactiveWorkout),
            plans = emptyList(),
        )
        val incomingInactiveWorkout = inactiveWorkout.copy(
            isActive = true,
            workoutComponents = listOf(
                exercise(equipmentId = UUID.randomUUID()),
            ),
        )

        val merged = localStore.mergeWatchWorkoutDefinitionUpdate(
            store(
                workouts = listOf(activeWorkout, incomingInactiveWorkout, incomingOnlyDeletedWorkout),
                plans = emptyList(),
            ),
        )

        assertEquals(
            listOf(activeWorkout.id, inactiveWorkout.id),
            merged.workouts.map { it.id },
        )
        assertEquals(inactiveWorkout, merged.workout(inactiveWorkout.id))
    }

    @Test
    fun emptyIncomingSnapshotDoesNotErasePhoneState() {
        val plan = plan("Push")
        val localWorkout = workout("Phone workout", plan.id)
        val localStore = store(
            workouts = listOf(localWorkout),
            plans = listOf(plan.copy(workoutIds = listOf(localWorkout.id))),
            weightKg = 82.5,
            birthDateYear = 1991,
        )
        val staleEmptyWatchSnapshot = store(
            workouts = emptyList(),
            plans = emptyList(),
            weightKg = 60.0,
            birthDateYear = 1970,
        )

        assertEquals(localStore, localStore.mergeWatchWorkoutDefinitionUpdate(staleEmptyWatchSnapshot))
    }

    @Test
    fun watchEquipmentUpdateKeepsPhoneDetachedMembershipAndAppliesWorkoutEdit() {
        val plan = plan("Push")
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val exerciseId = UUID.randomUUID()
        val workout = workout(
            name = "Push day",
            workoutPlanId = plan.id,
            components = listOf(exercise(id = exerciseId, equipmentId = equipmentA.id)),
        )
        val repository = WorkoutStoreRepository(directory.toFile())
        repository.saveWorkoutStore(
            store(
                workouts = listOf(workout.copy(workoutPlanId = null)),
                plans = listOf(plan.copy(workoutIds = emptyList())),
                equipments = listOf(equipmentA, equipmentB),
            ),
        )
        val staleWatchSnapshot = store(
            workouts = listOf(
                workout.copy(
                    name = "Push day edited on watch",
                    workoutComponents = listOf(exercise(id = exerciseId, equipmentId = equipmentB.id)),
                ),
            ),
            plans = listOf(
                plan.copy(
                    name = "Stale watch plan name",
                    workoutIds = listOf(workout.id),
                ),
            ),
            equipments = listOf(equipmentA),
        )
        val phoneStore = repository.getWorkoutStore()

        repository.saveWorkoutStore(
            phoneStore.mergeWatchWorkoutDefinitionUpdate(staleWatchSnapshot),
        )

        val applied = repository.getWorkoutStore()
        assertNull(applied.workout(workout.id).workoutPlanId)
        assertTrue(applied.plan(plan.id).workoutIds.isEmpty())
        assertEquals("Push", applied.plan(plan.id).name)
        assertEquals("Push day", applied.workout(workout.id).name)
        assertEquals(
            equipmentB.id,
            applied.workout(workout.id).exercise(exerciseId).equipmentId,
        )
    }

    @Test
    fun emptyPhoneStoreAdoptsTheWatchSnapshotUnchanged() {
        val plan = plan("Push")
        val workout = workout("Push day", plan.id)
        val watchSnapshot = store(
            workouts = listOf(workout),
            plans = listOf(plan.copy(workoutIds = listOf(workout.id))),
        )

        assertEquals(
            watchSnapshot,
            emptyStore().mergeWatchWorkoutDefinitionUpdate(watchSnapshot),
        )
    }

    @Test
    fun legacySnapshotDoesNotReplaceSettingsOrResurrectWorkoutsWhenPhoneHasNoWorkouts() {
        val localStore = store(
            workouts = emptyList(),
            plans = emptyList(),
            weightKg = 82.5,
            birthDateYear = 1991,
        )
        val staleWatchSnapshot = store(
            workouts = listOf(workout("Deleted on phone")),
            plans = listOf(plan("Stale plan")),
            weightKg = 60.0,
            birthDateYear = 1970,
        )

        assertEquals(localStore, localStore.mergeWatchWorkoutDefinitionUpdate(staleWatchSnapshot))
    }

    @Test
    fun progressedSessionEquipmentEditAppliesOnlyEquipmentAndPreservesPhoneDefinition() {
        val plan = plan("Push")
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val exerciseId = UUID.randomUUID()
        val phoneSetId = UUID.randomUUID()
        val phoneWorkout = workout(
            name = "Bench day",
            workoutPlanId = plan.id,
            components = listOf(
                exercise(
                    id = exerciseId,
                    equipmentId = equipmentA.id,
                    sets = listOf(weightSet(id = phoneSetId, reps = 8, weight = 100.0)),
                ),
            ),
        )
        val phoneStore = store(
            workouts = listOf(phoneWorkout),
            plans = listOf(plan.copy(workoutIds = listOf(phoneWorkout.id))),
            equipments = listOf(equipmentA, equipmentB),
            weightKg = 82.5,
            birthDateYear = 1991,
        )
        // The watch's session copy is hydrated with progression: same definition, different sets.
        val watchExercise = exercise(
            id = exerciseId,
            equipmentId = equipmentA.id,
            sets = listOf(weightSet(id = phoneSetId, reps = 10, weight = 110.0)),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = phoneWorkout,
            exercise = watchExercise,
            newEquipmentId = equipmentB.id,
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        val merged = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        val mergedExercise = merged.workout(phoneWorkout.id).exercise(exerciseId)
        assertEquals(equipmentB.id, mergedExercise.equipmentId)
        assertEquals(listOf(100.0), mergedExercise.sets.map { (it as WeightSet).weight })
        assertEquals(listOf(8), mergedExercise.sets.map { (it as WeightSet).reps })
        assertEquals(phoneStore.workoutPlans, merged.workoutPlans)
        assertEquals(phoneStore.equipments, merged.equipments)
        assertEquals(82.5, merged.weightKg, 0.0)
        assertEquals(1991, merged.birthDateYear)
    }

    @Test
    fun calibrationEditAppliesWhileKeepingUnrelatedPhoneEdits() {
        val pendingSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val phoneExercise = exercise(
            id = exerciseId,
            name = "Renamed on phone",
            notes = "Phone notes",
            equipmentId = UUID.randomUUID(),
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = pendingSetId,
                    reps = 10,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
                weightSet(
                    id = workSetId,
                    reps = 10,
                    weight = 100.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
            ),
        )
        val phoneWorkout = workout(
            name = "Renamed workout on phone",
            components = listOf(phoneExercise),
        )
        val phoneStore = store(workouts = listOf(phoneWorkout), plans = emptyList())
        val watchExercise = phoneExercise.copy(
            name = "Pre-edit name",
            notes = "",
            sets = listOf(
                weightSet(
                    id = pendingSetId,
                    reps = 8,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
                weightSet(
                    id = workSetId,
                    reps = 8,
                    weight = 100.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
            ),
        )
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = phoneWorkout,
                persistedExercise = watchExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = pendingSetId,
                        reps = 8,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                    weightSet(
                        id = workSetId,
                        reps = 8,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        val merged = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        val mergedWorkout = merged.workout(phoneWorkout.id)
        val mergedExercise = mergedWorkout.exercise(exerciseId)
        assertEquals("Renamed workout on phone", mergedWorkout.name)
        assertEquals("Renamed on phone", mergedExercise.name)
        assertEquals("Phone notes", mergedExercise.notes)
        assertEquals(phoneExercise.equipmentId, mergedExercise.equipmentId)
        assertFalse(mergedExercise.requiresLoadCalibration)
        assertEquals(listOf(90.0, 90.0), mergedExercise.sets.map { (it as WeightSet).weight })
        assertEquals(listOf(10, 10), mergedExercise.sets.map { (it as WeightSet).reps })
        assertEquals(
            listOf(SetSubCategory.WorkSet, SetSubCategory.WorkSet),
            mergedExercise.sets.map { (it as WeightSet).subCategory },
        )
    }

    @Test
    fun sameEquipmentFieldEditedOnPhoneIsReportedAsConflict() {
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val equipmentC = equipment("Dumbbell C")
        val exerciseId = UUID.randomUUID()
        val phoneWorkout = workout(
            name = "Workout",
            components = listOf(
                exercise(id = exerciseId, equipmentId = equipmentC.id),
            ),
        )
        val phoneStore = store(
            workouts = listOf(phoneWorkout),
            plans = emptyList(),
            equipments = listOf(equipmentA, equipmentB, equipmentC),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = phoneWorkout,
            exercise = exercise(id = exerciseId, equipmentId = equipmentA.id),
            newEquipmentId = equipmentB.id,
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue((result as WatchWorkoutDefinitionEditResult.Rejected).reason.contains("Conflicting equipment"))
        assertEquals(equipmentC.id, phoneStore.workout(phoneWorkout.id).exercise(exerciseId).equipmentId)
    }

    @Test
    fun sameCalibrationSetEditedOnPhoneIsReportedAsConflict() {
        val setId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val phoneExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = setId,
                    weight = 80.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val phoneWorkout = workout(name = "Workout", components = listOf(phoneExercise))
        val phoneStore = store(workouts = listOf(phoneWorkout), plans = emptyList())
        val watchSet = weightSet(
            id = setId,
            weight = 100.0,
            subCategory = SetSubCategory.CalibrationPendingSet,
        )
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = phoneWorkout,
                persistedExercise = phoneExercise.copy(sets = listOf(watchSet)),
                calibratedSets = listOf(
                    weightSet(
                        id = setId,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue((result as WatchWorkoutDefinitionEditResult.Rejected).reason.contains("Conflicting calibration"))
        assertEquals(80.0, (phoneStore.workout(phoneWorkout.id).exercise(exerciseId).sets.single() as WeightSet).weight, 0.0)
    }

    @Test
    fun calibrationThatOnlyClearsTheFlagIsAppliedWhenNoPendingSetsRemain() {
        val setId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val phoneExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = setId,
                    weight = 100.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
            ),
        )
        val phoneWorkout = workout(name = "Workout", components = listOf(phoneExercise))
        val phoneStore = store(workouts = listOf(phoneWorkout), plans = emptyList())
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = phoneWorkout,
                persistedExercise = phoneExercise,
                calibratedSets = phoneExercise.sets,
            ),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        val merged = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        assertFalse(merged.workout(phoneWorkout.id).exercise(exerciseId).requiresLoadCalibration)
        assertEquals(
            100.0,
            (merged.workout(phoneWorkout.id).exercise(exerciseId).sets.single() as WeightSet).weight,
            0.0,
        )
    }

    @Test
    fun calibrationThatLeavesPendingSetsIsRejected() {
        val resolvedSetId = UUID.randomUUID()
        val stillPendingSetId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val phoneExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = resolvedSetId,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
                weightSet(
                    id = stillPendingSetId,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val phoneWorkout = workout(name = "Workout", components = listOf(phoneExercise))
        val phoneStore = store(workouts = listOf(phoneWorkout), plans = emptyList())
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = phoneWorkout,
                persistedExercise = phoneExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = resolvedSetId,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                    weightSet(
                        id = stillPendingSetId,
                        weight = 100.0,
                        subCategory = SetSubCategory.CalibrationPendingSet,
                    ),
                ),
            ),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue((result as WatchWorkoutDefinitionEditResult.Rejected).reason.contains("pending"))
        assertEquals(phoneWorkout, phoneStore.workout(phoneWorkout.id))
    }

    @Test
    fun calibrationDetectsConcurrentPhoneEquipmentChange() {
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val equipmentC = equipment("Dumbbell C")
        val setId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val phoneExercise = exercise(
            id = exerciseId,
            equipmentId = equipmentC.id,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = setId,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val phoneWorkout = workout(name = "Workout", components = listOf(phoneExercise))
        val phoneStore = store(
            workouts = listOf(phoneWorkout),
            plans = emptyList(),
            equipments = listOf(equipmentA, equipmentB, equipmentC),
        )
        val watchExercise = phoneExercise.copy(equipmentId = equipmentA.id)
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = phoneWorkout,
                persistedExercise = watchExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = setId,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        assertEquals(equipmentA.id, intent.baseEquipmentId)
        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue((result as WatchWorkoutDefinitionEditResult.Rejected).reason.contains("Conflicting equipment"))
        assertEquals(equipmentC.id, phoneStore.workout(phoneWorkout.id).exercise(exerciseId).equipmentId)
        assertEquals(
            SetSubCategory.CalibrationPendingSet,
            (phoneStore.workout(phoneWorkout.id).exercise(exerciseId).sets.single() as WeightSet).subCategory,
        )
    }

    @Test
    fun localDefinitionPersistenceIgnoresSessionHydratedWorkoutFields() {
        val setId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val localExercise = exercise(
            id = exerciseId,
            name = "Phone exercise name",
            notes = "Phone notes",
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = setId,
                    reps = 10,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val localWorkout = workout(
            name = "Phone workout name",
            description = "Phone description",
            components = listOf(localExercise),
        )
        val localStore = store(workouts = listOf(localWorkout), plans = emptyList())
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = localWorkout,
                persistedExercise = localExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = setId,
                        reps = 6,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        val result = localStore.applyWatchWorkoutDefinitionEditLocally(intent)

        val updated = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        val updatedWorkout = updated.workout(localWorkout.id)
        val updatedExercise = updatedWorkout.exercise(exerciseId)
        assertEquals("Phone workout name", updatedWorkout.name)
        assertEquals("Phone description", updatedWorkout.description)
        assertEquals("Phone exercise name", updatedExercise.name)
        assertEquals("Phone notes", updatedExercise.notes)
        assertEquals(listOf(10), updatedExercise.sets.map { (it as WeightSet).reps })
        assertEquals(listOf(90.0), updatedExercise.sets.map { (it as WeightSet).weight })
        assertEquals(
            listOf(SetSubCategory.WorkSet),
            updatedExercise.sets.map { (it as WeightSet).subCategory },
        )
        assertFalse(updatedExercise.requiresLoadCalibration)
    }

    @Test
    fun calibrationBaselineUsesPersistedDefinitionWhileTargetsUseSessionResults() {
        val pendingSetId = UUID.randomUUID()
        val workSetId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val equipmentId = UUID.randomUUID()
        val persistedExercise = exercise(
            id = exerciseId,
            equipmentId = equipmentId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = pendingSetId,
                    reps = 10,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
                weightSet(
                    id = workSetId,
                    reps = 10,
                    weight = 100.0,
                    subCategory = SetSubCategory.WorkSet,
                ),
            ),
        )
        val persistedWorkout = workout(
            name = "Persisted definition",
            components = listOf(persistedExercise),
        )
        val phoneStoreSameDefinition = store(
            workouts = listOf(persistedWorkout),
            plans = emptyList(),
        )
        // Session hydration changed the pre-edit values on the watch; they must not become the
        // conflict baseline sent to the phone.
        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = persistedWorkout,
                persistedExercise = persistedExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = pendingSetId,
                        reps = 10,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                    weightSet(
                        id = workSetId,
                        reps = 10,
                        weight = 88.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        assertEquals(setOf(pendingSetId, workSetId), intent.setEdits.map { it.setId }.toSet())
        assertEquals(listOf(100.0, 100.0), intent.setEdits.map { it.baseWeight })
        assertEquals(listOf(90.0, 88.0), intent.setEdits.map { it.newWeight })
        assertEquals(equipmentId, intent.baseEquipmentId)
        assertTrue(intent.baseRequiresLoadCalibration)

        val result = phoneStoreSameDefinition.applyWatchWorkoutDefinitionEdit(intent)

        val merged = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        val mergedExercise = merged.workout(persistedWorkout.id).exercise(exerciseId)
        assertEquals(listOf(90.0, 88.0), mergedExercise.sets.map { (it as WeightSet).weight })
        assertFalse(mergedExercise.requiresLoadCalibration)
    }

    @Test
    fun calibrationIntentOnlyEmitsEditsForSetIdsPresentInPersistedDefinition() {
        val persistedSetId = UUID.randomUUID()
        val sessionOnlySetId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val persistedExercise = exercise(
            id = exerciseId,
            requiresLoadCalibration = true,
            sets = listOf(
                weightSet(
                    id = persistedSetId,
                    weight = 100.0,
                    subCategory = SetSubCategory.CalibrationPendingSet,
                ),
            ),
        )
        val persistedWorkout = workout(name = "Workout", components = listOf(persistedExercise))

        val intent = requireNotNull(
            WatchWorkoutDefinitionEditIntent.calibration(
                persistedWorkout = persistedWorkout,
                persistedExercise = persistedExercise,
                calibratedSets = listOf(
                    weightSet(
                        id = persistedSetId,
                        weight = 90.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                    weightSet(
                        id = sessionOnlySetId,
                        weight = 70.0,
                        subCategory = SetSubCategory.WorkSet,
                    ),
                ),
            ),
        )

        assertEquals(listOf(persistedSetId), intent.setEdits.map { it.setId })
    }

    @Test
    fun localEquipmentPersistenceKeepsStoreDefinitionFields() {
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val setId = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val localExercise = exercise(
            id = exerciseId,
            name = "Phone exercise name",
            notes = "Phone notes",
            equipmentId = equipmentA.id,
            sets = listOf(weightSet(id = setId, reps = 10, weight = 100.0)),
        )
        val localWorkout = workout(
            name = "Phone workout name",
            description = "Phone description",
            components = listOf(localExercise),
        )
        val localStore = store(
            workouts = listOf(localWorkout),
            plans = emptyList(),
            equipments = listOf(equipmentA, equipmentB),
        )
        // The watch's selected workout is session-hydrated with different values.
        val sessionHydratedWorkout = localWorkout.copy(
            name = "Hydrated name",
            workoutComponents = listOf(
                localExercise.copy(
                    name = "Hydrated exercise",
                    notes = "",
                    sets = listOf(weightSet(id = setId, reps = 6, weight = 110.0)),
                ),
            ),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = sessionHydratedWorkout,
            exercise = sessionHydratedWorkout.exercise(exerciseId),
            newEquipmentId = equipmentB.id,
        )

        val result = localStore.applyWatchWorkoutDefinitionEditLocally(intent)

        val updated = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        val updatedWorkout = updated.workout(localWorkout.id)
        val updatedExercise = updatedWorkout.exercise(exerciseId)
        assertEquals("Phone workout name", updatedWorkout.name)
        assertEquals("Phone description", updatedWorkout.description)
        assertEquals("Phone exercise name", updatedExercise.name)
        assertEquals("Phone notes", updatedExercise.notes)
        assertEquals(listOf(10), updatedExercise.sets.map { (it as WeightSet).reps })
        assertEquals(listOf(100.0), updatedExercise.sets.map { (it as WeightSet).weight })
        assertEquals(equipmentB.id, updatedExercise.equipmentId)
        assertEquals(localStore.workoutPlans, updated.workoutPlans)
    }

    @Test
    fun editAgainstSupersededWorkoutVersionIsRejected() {
        val globalId = UUID.randomUUID()
        val oldVersionId = UUID.randomUUID()
        val newVersionId = UUID.randomUUID()
        val oldWorkout = workout("Old version").copy(
            id = oldVersionId,
            globalId = globalId,
            isActive = false,
            nextVersionId = newVersionId,
        )
        val newWorkout = workout("New version").copy(
            id = newVersionId,
            globalId = globalId,
            previousVersionId = oldVersionId,
        )
        val phoneStore = store(
            workouts = listOf(oldWorkout, newWorkout),
            plans = emptyList(),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = oldWorkout,
            exercise = exercise(equipmentId = UUID.randomUUID()),
            newEquipmentId = UUID.randomUUID(),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue((result as WatchWorkoutDefinitionEditResult.Rejected).reason.contains("Stale workout version"))
        assertEquals(newWorkout, phoneStore.workout(newVersionId))
    }

    @Test
    fun equipmentEditPreservesUngroupedMembershipAndUnrelatedWorkouts() {
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val plan = plan("Push")
        val exerciseId = UUID.randomUUID()
        val ungroupedWorkout = workout(
            name = "Ungrouped",
            workoutPlanId = null,
            components = listOf(exercise(id = exerciseId, equipmentId = equipmentA.id)),
        )
        val localOnlyWorkout = workout(name = "Phone-only", workoutPlanId = plan.id)
        val phoneStore = store(
            workouts = listOf(ungroupedWorkout, localOnlyWorkout),
            plans = listOf(plan.copy(workoutIds = listOf(localOnlyWorkout.id))),
            equipments = listOf(equipmentA, equipmentB),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = ungroupedWorkout,
            exercise = ungroupedWorkout.exercise(exerciseId),
            newEquipmentId = equipmentB.id,
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        val merged = (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore
        assertNull(merged.workout(ungroupedWorkout.id).workoutPlanId)
        assertTrue(merged.plan(plan.id).workoutIds == listOf(localOnlyWorkout.id))
        assertEquals(localOnlyWorkout, merged.workout(localOnlyWorkout.id))
        assertEquals(equipmentB.id, merged.workout(ungroupedWorkout.id).exercise(exerciseId).equipmentId)
    }

    @Test
    fun structuredEquipmentUpdateKeepsDetachedMembershipAfterRepositorySave() {
        val plan = plan("Push")
        val exerciseId = UUID.randomUUID()
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val detachedWorkout = workout(
            name = "Push day",
            workoutPlanId = null,
            components = listOf(exercise(id = exerciseId, equipmentId = equipmentA.id)),
        )
        val repository = WorkoutStoreRepository(directory.toFile())
        repository.saveWorkoutStore(
            store(
                workouts = listOf(detachedWorkout),
                plans = listOf(plan.copy(workoutIds = emptyList())),
                equipments = listOf(equipmentA, equipmentB),
            ),
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = detachedWorkout,
            exercise = detachedWorkout.exercise(exerciseId),
            newEquipmentId = equipmentB.id,
        )

        val result = repository.getWorkoutStore().applyWatchWorkoutDefinitionEdit(intent)
        repository.saveWorkoutStore(
            (result as WatchWorkoutDefinitionEditResult.Applied).workoutStore,
        )

        val applied = repository.getWorkoutStore()
        assertNull(applied.workout(detachedWorkout.id).workoutPlanId)
        assertTrue(applied.plan(plan.id).workoutIds.isEmpty())
        assertEquals("Push", applied.plan(plan.id).name)
        assertEquals(
            equipmentB.id,
            applied.workout(detachedWorkout.id).exercise(exerciseId).equipmentId,
        )
    }

    @Test
    fun structuredEditOnPhoneWithoutTargetWorkoutIsRejectedWithoutTouchingSettings() {
        val phoneStore = store(
            workouts = emptyList(),
            plans = emptyList(),
            equipments = listOf(equipment("Dumbbell A")),
            weightKg = 82.5,
            birthDateYear = 1991,
        )
        val intent = WatchWorkoutDefinitionEditIntent.equipment(
            workout = workout("Watch-only"),
            exercise = exercise(equipmentId = UUID.randomUUID()),
            newEquipmentId = UUID.randomUUID(),
        )

        val result = phoneStore.applyWatchWorkoutDefinitionEdit(intent)

        assertTrue(result is WatchWorkoutDefinitionEditResult.Rejected)
        assertTrue(phoneStore.workouts.isEmpty())
        assertTrue(phoneStore.workoutPlans.isEmpty())
        assertEquals(82.5, phoneStore.weightKg, 0.0)
        assertEquals(1991, phoneStore.birthDateYear)
    }

    @Test
    fun editIntentCodecRoundTripsCalibrationPayload() {
        val setId = UUID.randomUUID()
        val intent = WatchWorkoutDefinitionEditIntent(
            workoutId = UUID.randomUUID(),
            workoutGlobalId = UUID.randomUUID(),
            exerciseId = UUID.randomUUID(),
            kind = WatchWorkoutDefinitionEditKind.LOAD_CALIBRATION,
            baseEquipmentId = UUID.randomUUID(),
            baseRequiresLoadCalibration = true,
            setEdits = listOf(
                WatchWorkoutSetEdit(
                    setId = setId,
                    setKind = WatchWorkoutSetKind.WEIGHT,
                    baseWeight = 100.0,
                    newWeight = 90.0,
                    baseSubCategory = SetSubCategory.CalibrationPendingSet,
                    newSubCategory = SetSubCategory.WorkSet,
                ),
            ),
        )

        assertEquals(
            intent,
            WatchWorkoutDefinitionEditCodec.decode(
                WatchWorkoutDefinitionEditCodec.encode(intent),
            ),
        )
    }

    @Test
    fun legacySnapshotWithoutIntentKeepsConservativeBehaviorForProgressedSets() {
        val equipmentA = equipment("Dumbbell A")
        val equipmentB = equipment("Dumbbell B")
        val exerciseId = UUID.randomUUID()
        val phoneWorkout = workout(
            name = "Workout",
            components = listOf(
                exercise(
                    id = exerciseId,
                    equipmentId = equipmentA.id,
                    sets = listOf(weightSet(reps = 8, weight = 100.0)),
                ),
            ),
        )
        val phoneStore = store(
            workouts = listOf(phoneWorkout),
            plans = emptyList(),
            equipments = listOf(equipmentA, equipmentB),
        )
        val sessionHydratedSnapshot = store(
            workouts = listOf(
                phoneWorkout.copy(
                    workoutComponents = listOf(
                        exercise(
                            id = exerciseId,
                            equipmentId = equipmentB.id,
                            sets = listOf(weightSet(reps = 10, weight = 110.0)),
                        ),
                    ),
                ),
            ),
            plans = emptyList(),
        )

        val merged = phoneStore.mergeWatchWorkoutDefinitionUpdate(sessionHydratedSnapshot)

        assertEquals(phoneWorkout, merged.workout(phoneWorkout.id))
    }

    private fun WorkoutStore.workout(id: UUID): Workout = workouts.single { it.id == id }

    private fun WorkoutStore.plan(id: UUID): WorkoutPlan = workoutPlans.single { it.id == id }

    private fun Workout.exercise(id: UUID): Exercise =
        workoutComponents.filterIsInstance<Exercise>().single { it.id == id }

    private fun plan(name: String, order: Int = 0) = WorkoutPlan(
        id = UUID.randomUUID(),
        name = name,
        workoutIds = emptyList(),
        order = order,
    )

    private fun equipment(name: String) = Dumbbell(
        id = UUID.randomUUID(),
        name = name,
        availableDumbbells = listOf(BaseWeight(20.0)),
    )

    private fun workout(
        name: String,
        workoutPlanId: UUID? = null,
        order: Int = 0,
        components: List<WorkoutComponent> = emptyList(),
        description: String = "",
    ) = Workout(
        id = UUID.randomUUID(),
        name = name,
        description = description,
        workoutComponents = components,
        order = order,
        creationDate = LocalDate.of(2026, 1, 1),
        globalId = UUID.randomUUID(),
        type = 0,
        workoutPlanId = workoutPlanId,
    )

    private fun exercise(
        id: UUID = UUID.randomUUID(),
        equipmentId: UUID? = null,
        name: String = "Bench press",
        notes: String = "",
        sets: List<Set> = emptyList(),
        requiresLoadCalibration: Boolean = false,
    ) = Exercise(
        id = id,
        enabled = true,
        name = name,
        notes = notes,
        sets = sets,
        exerciseType = ExerciseType.WEIGHT,
        minReps = 8,
        maxReps = 12,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = equipmentId,
        bodyWeightPercentage = null,
        requiresLoadCalibration = requiresLoadCalibration,
    )

    private fun weightSet(
        id: UUID = UUID.randomUUID(),
        reps: Int = 8,
        weight: Double = 100.0,
        subCategory: SetSubCategory = SetSubCategory.WorkSet,
    ) = WeightSet(
        id = id,
        reps = reps,
        weight = weight,
        subCategory = subCategory,
    )

    private fun store(
        workouts: List<Workout>,
        plans: List<WorkoutPlan>,
        equipments: List<WeightLoadedEquipment> = emptyList(),
        weightKg: Double = 80.0,
        birthDateYear: Int = 1990,
    ) = WorkoutStore(
        workouts = workouts,
        workoutPlans = plans,
        equipments = equipments,
        birthDateYear = birthDateYear,
        weightKg = weightKg,
        progressionPercentageAmount = 0.0,
    )

    private fun emptyStore() = WorkoutStore(
        workouts = emptyList(),
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        birthDateYear = 0,
        weightKg = 0.0,
        progressionPercentageAmount = 0.0,
    )
}
