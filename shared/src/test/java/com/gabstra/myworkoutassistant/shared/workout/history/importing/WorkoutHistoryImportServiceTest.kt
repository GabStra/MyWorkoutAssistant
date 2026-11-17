package com.gabstra.myworkoutassistant.shared.workout.history.importing

import android.content.Context
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryOrigin
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.backupGson
import com.gabstra.myworkoutassistant.shared.fromAppBackupToJSON
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.equipments.AccessoryEquipment
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.workout.history.knownDurationSecondsOrNull
import com.gabstra.myworkoutassistant.shared.workout.history.knownStartTimeOrNull
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workout.presentation.resolveRecurringPrescriptionProgress
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedRestStore
import com.gabstra.myworkoutassistant.shared.stores.DefaultExecutedSetStore
import com.gabstra.myworkoutassistant.shared.workout.session.WorkoutSessionLifecycleService
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [30])
class WorkoutHistoryImportServiceTest {
    private lateinit var database: AppDatabase
    private val profileId = "history-import-profile"
    private val sessionId = UUID.fromString("00ed9a5e-62bd-4fa4-9f88-5130fa3b89e5")
    private val trackId = UUID.fromString("a282f145-0caf-4aeb-93e6-7e0149efebea")
    private val exerciseId = UUID.fromString("8c0318b2-1732-4a59-807a-b55474bb4ab6")
    private val setIds = listOf(
        UUID.fromString("5aa13e8b-87db-42f1-a550-f4288b3197d0"),
        UUID.fromString("7b40dd1c-b833-4994-88d2-b246c1a2d8c8"),
        UUID.fromString("855c2775-eaa7-4d60-87c7-a47c012b90ce"),
    )

    @Before
    fun setup() {
        val context = ApplicationProvider.getApplicationContext<Context>()
        database = Room.inMemoryDatabaseBuilder(context, AppDatabase::class.java)
            .allowMainThreadQueries()
            .build()
    }

    @After
    fun tearDown() {
        database.close()
    }

    @Test
    fun appendIsIdempotentAndImportedCompletionAdvancesFamilyWithoutInventingTiming() = runBlocking {
        val fixture = fixture()
        val payload = fixture.payload
        val first = payload.workoutHistories.single()
        assertNull(first.knownStartTimeOrNull())
        assertNull(first.knownDurationSecondsOrNull())

        val firstAppend = WorkoutHistoryImportService.append(database, fixture.store, profileId, payload)
        assertEquals(1, firstAppend.insertedHistories)
        assertEquals(3, firstAppend.insertedSets)
        assertEquals(0, WorkoutHistoryImportService.append(database, fixture.store, profileId, payload).insertedHistories)
        assertEquals(0, WorkoutHistoryImportService.append(database, fixture.store, profileId, payload).insertedSets)

        val saved = database.workoutHistoryDao().getWorkoutHistoryById(first.id)!!
        assertEquals(WorkoutHistoryOrigin.USER_IMPORTED, saved.origin)
        assertEquals(LocalDate.of(2026, 11, 13), saved.date)
        assertNull(saved.knownStartTimeOrNull())
        assertNull(saved.knownDurationSecondsOrNull())

        val progress = resolveRecurringPrescriptionProgress(
            workouts = fixture.store.workouts,
            histories = database.workoutHistoryDao().getAllWorkoutHistories(),
        ).getValue(sessionId)
        assertEquals(fixture.store.workouts[0].id, progress.lastCompletedWorkoutId)
        assertEquals(fixture.store.workouts[1].id, progress.suggestedWorkoutId)
        assertEquals(3, database.setHistoryDao().getSetHistoriesByWorkoutHistoryId(first.id).size)

        val weekTwo = fixture.store.workouts[1]
        val weekTwoExercise = weekTwo.workoutComponents.single() as Exercise
        val loaded = WorkoutSessionLifecycleService(
            executedSetStore = DefaultExecutedSetStore(),
            executedRestStore = DefaultExecutedRestStore(),
            setHistoryDao = { database.setHistoryDao() },
            restHistoryDao = { database.restHistoryDao() },
            workoutHistoryDao = { database.workoutHistoryDao() },
        ).loadWorkoutHistory(weekTwo, fixture.store.workouts, fixture.store.workouts)
        val carriedRow = loaded.latestSetHistoryByExerciseAndSetId[weekTwoExercise.id to weekTwoExercise.sets.first().id]
        assertEquals(40.0, (carriedRow!!.setData as WeightSetData).actualWeight, 0.0)
    }

    @Test
    fun packageJsonRoundTripPreservesUnknownTimingAndActualSetRows() {
        val payload = fixture().payload
        val decoded = WorkoutHistoryImportPackage.fromJson(payload.toJson())
        assertEquals(payload, decoded)
        assertEquals(WorkoutHistoryImportPackage.FORMAT, decoded.format)
        assertEquals(1, decoded.formatVersion)
        assertEquals(listOf(40.0, 40.0, 40.0), decoded.setHistories.map { (it.setData as WeightSetData).actualWeight })
    }

    @Test
    fun profileBackupRoundTripPreservesImportedHistoryAndSubstitutionSnapshot() {
        val base = fixture()
        val payload = base.payload.copy(
            setHistories = base.payload.setHistories.mapIndexed { index, row ->
                if (index == 0) row.copy(exerciseNameSnapshot = "Press — documented substitution") else row
            },
        )
        val backup = AppBackup(
            WorkoutStore = base.store,
            WorkoutHistories = payload.workoutHistories,
            SetHistories = payload.setHistories,
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
            ProfileId = profileId,
        )
        val restored = fromJSONtoAppBackup(fromAppBackupToJSON(backup))
        assertEquals(payload.workoutHistories, restored.WorkoutHistories)
        assertEquals(payload.setHistories, restored.SetHistories)
        assertEquals("Press — documented substitution", restored.SetHistories.first().exerciseNameSnapshot)
    }

    @Test
    fun legacyHistoryJsonDefaultsToRecordedAndKnownTiming() {
        val history = fixture().payload.workoutHistories.single().copy(
            origin = WorkoutHistoryOrigin.RECORDED,
            startTimeKnown = true,
            durationKnown = true,
        )
        // Simulate JSON produced before the imported-history metadata existed.
        val legacyObject = com.google.gson.JsonParser.parseString(backupGson().toJson(history)).asJsonObject.apply {
            remove("origin")
            remove("startTimeKnown")
            remove("durationKnown")
        }
        val decoded = backupGson().fromJson(legacyObject, WorkoutHistory::class.java)
        assertEquals(WorkoutHistoryOrigin.RECORDED, decoded.origin)
        assertEquals(true, decoded.startTimeKnown)
        assertEquals(true, decoded.durationKnown)
        assertEquals(history.startTime, decoded.knownStartTimeOrNull())
        assertEquals(history.duration, decoded.knownDurationSecondsOrNull())
    }

    @Test
    fun packageCannotBeAppendedToAnotherProfileOrOverwriteExistingHistory() = runBlocking {
        val fixture = fixture()
        val payload = fixture.payload
        assertThrows(IllegalArgumentException::class.java) {
            WorkoutHistoryImportService.validate(fixture.store, "other-profile", payload)
        }
        WorkoutHistoryImportService.append(database, fixture.store, profileId, payload)
        val conflicting = payload.copy(
            workoutHistories = payload.workoutHistories.map {
                it.copy(date = it.date.plusDays(1), startTime = it.startTime.plusDays(1))
            },
        )
        assertThrows(IllegalArgumentException::class.java) {
            runBlocking { WorkoutHistoryImportService.append(database, fixture.store, profileId, conflicting) }
        }
        assertEquals(1, database.workoutHistoryDao().getAllWorkoutHistories().size)
    }

    @Test
    fun equipmentSubstitutionRequiresExplicitPerformedNameAndKnownEquipment() {
        val base = fixture()
        val payload = base.payload
        val prescribedEquipmentId = UUID.randomUUID()
        val performedEquipmentId = UUID.randomUUID()
        val workout = base.store.workouts.first()
        val prescribedExercise = (workout.workoutComponents.single() as Exercise).copy(
            equipmentId = prescribedEquipmentId,
        )
        val store = base.store.copy(
            workouts = listOf(workout.copy(workoutComponents = listOf(prescribedExercise))) + base.store.workouts.drop(1),
            accessoryEquipments = listOf(AccessoryEquipment(prescribedEquipmentId, "Band")),
            equipments = listOf(Dumbbell(performedEquipmentId, "Dumbbell", listOf(BaseWeight(5.5)))),
        )
        val validSubstitution = payload.copy(
            setHistories = payload.setHistories.map {
                it.copy(
                    equipmentIdSnapshot = performedEquipmentId,
                    equipmentNameSnapshot = "Dumbbell",
                    equipmentTypeSnapshot = EquipmentType.DUMBBELL.name,
                    exerciseNameSnapshot = "Press — dumbbell substitution",
                )
            },
        )
        WorkoutHistoryImportService.validate(store, profileId, validSubstitution)

        val unnamed = validSubstitution.copy(
            setHistories = validSubstitution.setHistories.map { it.copy(exerciseNameSnapshot = null) },
        )
        assertThrows(IllegalArgumentException::class.java) {
            WorkoutHistoryImportService.validate(store, profileId, unnamed)
        }
    }

    @Test
    fun externalOnlyBodyweightLoadScopeIsExplicitAndKeptAsActualMeasurement() {
        val workoutId = UUID.randomUUID()
        val globalId = UUID.randomUUID()
        val session = UUID.randomUUID()
        val exerciseId = UUID.randomUUID()
        val setId = UUID.randomUUID()
        val track = UUID.randomUUID()
        val actualDumbbellId = UUID.randomUUID()
        val exercise = Exercise(
            id = exerciseId,
            enabled = true,
            name = "Weighted crunch",
            notes = "",
            sets = listOf(BodyWeightSet(setId, reps = 12, additionalWeight = 0.0)),
            exerciseType = ExerciseType.BODY_WEIGHT,
            minReps = 12,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = actualDumbbellId,
            bodyWeightPercentage = 0.35,
            recurringExerciseId = track,
        )
        val workout = Workout(
            id = workoutId,
            name = "Week 1 B",
            description = "",
            workoutComponents = listOf(exercise),
            order = 1,
            creationDate = LocalDate.of(2026, 10, 1),
            globalId = globalId,
            type = 0,
            recurringSessionId = session,
            prescriptionOrdinal = 1,
        )
        val history = WorkoutHistory(
            id = UUID.randomUUID(),
            workoutId = workoutId,
            date = LocalDate.of(2026, 11, 14),
            time = LocalTime.MIDNIGHT,
            startTime = LocalDateTime.of(2026, 11, 14, 0, 0),
            duration = 5_400,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = globalId,
            recurringSessionId = session,
            origin = WorkoutHistoryOrigin.USER_IMPORTED,
            startTimeKnown = false,
            durationKnown = true,
        )
        val row = SetHistory(
            id = UUID.randomUUID(),
            workoutHistoryId = history.id,
            exerciseId = exerciseId,
            equipmentIdSnapshot = actualDumbbellId,
            equipmentNameSnapshot = "Dumbbell",
            equipmentTypeSnapshot = EquipmentType.DUMBBELL.name,
            setId = setId,
            order = 0u,
            startTime = null,
            endTime = null,
            setData = BodyWeightSetData(
                actualReps = 12,
                additionalWeight = 3.5,
                relativeBodyWeightInKg = 0.0,
                volume = 42.0,
                bodyWeightPercentageSnapshot = 0.0,
            ),
            skipped = false,
            recurringExerciseId = track,
            exerciseTypeSnapshot = ExerciseType.BODY_WEIGHT.name,
            exerciseNameSnapshot = "Weighted crunch — external load only",
        )
        val store = WorkoutStore(
            workouts = listOf(workout),
            equipments = listOf(Dumbbell(actualDumbbellId, "Dumbbell", listOf(BaseWeight(5.5)))),
            birthDateYear = 1990,
            weightKg = 60.0,
            progressionPercentageAmount = 0.0,
        )
        val payload = WorkoutHistoryImportPackage(
            profileId = profileId,
            workoutHistories = listOf(history),
            setHistories = listOf(row),
        )
        WorkoutHistoryImportService.validate(store, profileId, payload)
        val roundTripRow = WorkoutHistoryImportPackage.fromJson(payload.toJson()).setHistories.single()
        val roundTripData = roundTripRow.setData as BodyWeightSetData
        assertEquals(3.5, roundTripData.additionalWeight, 0.0)
        assertEquals(0.0, roundTripData.relativeBodyWeightInKg, 0.0)
        assertEquals(0.0, roundTripData.bodyWeightPercentageSnapshot!!, 0.0)
        assertEquals("Weighted crunch — external load only", roundTripRow.exerciseNameSnapshot)
    }

    private data class Fixture(val store: WorkoutStore, val payload: WorkoutHistoryImportPackage)

    private fun fixture(): Fixture {
        val recurringExercise = exercise()
        val weekOne = workout("Week 1", 1, recurringExercise)
        val weekTwo = workout("Week 2", 2, recurringExercise.copy(
            id = UUID.fromString("af66f17f-a018-4409-8a58-557886e35be2"),
            sets = setIds.mapIndexed { index, id -> WeightSet(id, reps = 9, weight = 40.0 + index) },
        ))
        val store = WorkoutStore(
            workouts = listOf(weekOne, weekTwo),
            birthDateYear = 1990,
            weightKg = 60.0,
            progressionPercentageAmount = 0.0,
        )
        val historyId = UUID.fromString("5149caf0-ad83-43f6-9dd5-38c1b7a0673e")
        val history = WorkoutHistory(
            id = historyId,
            workoutId = weekOne.id,
            date = LocalDate.of(2026, 11, 13),
            time = LocalTime.MIDNIGHT,
            startTime = LocalDateTime.of(2026, 11, 13, 0, 0),
            duration = 0,
            heartBeatRecords = emptyList(),
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = weekOne.globalId,
            recurringSessionId = sessionId,
            origin = WorkoutHistoryOrigin.USER_IMPORTED,
            startTimeKnown = false,
            durationKnown = false,
        )
        val sets = setIds.mapIndexed { index, id ->
            SetHistory(
                id = UUID.nameUUIDFromBytes("import-row-$index".toByteArray()),
                workoutHistoryId = historyId,
                exerciseId = exerciseId,
                setId = id,
                order = index.toUInt(),
                startTime = null,
                endTime = null,
                setData = WeightSetData(actualReps = 8, actualWeight = 40.0, volume = 320.0),
                skipped = false,
                recurringExerciseId = trackId,
                exerciseDefinitionIdSnapshot = null,
                exerciseTypeSnapshot = ExerciseType.WEIGHT.name,
            )
        }
        val payload = WorkoutHistoryImportPackage(
            profileId = profileId,
            workoutHistories = listOf(history),
            setHistories = sets,
        )
        WorkoutHistoryImportService.validate(store, profileId, payload)
        return Fixture(store, payload)
    }

    private fun exercise() = Exercise(
        id = exerciseId,
        enabled = true,
        name = "Press",
        notes = "",
        sets = setIds.map { WeightSet(it, reps = 8, weight = 40.0) },
        exerciseType = ExerciseType.WEIGHT,
        minReps = 8,
        maxReps = 8,
        lowerBoundMaxHRPercent = null,
        upperBoundMaxHRPercent = null,
        equipmentId = null,
        bodyWeightPercentage = null,
        recurringExerciseId = trackId,
    )

    private fun workout(name: String, ordinal: Int, exercise: Exercise) = Workout(
        id = UUID.nameUUIDFromBytes("$name-id".toByteArray()),
        name = name,
        description = "",
        workoutComponents = listOf(exercise),
        order = ordinal,
        creationDate = LocalDate.of(2026, 10, 1),
        globalId = UUID.nameUUIDFromBytes("$name-global".toByteArray()),
        type = 0,
        recurringSessionId = sessionId,
        prescriptionOrdinal = ordinal,
    )
}
