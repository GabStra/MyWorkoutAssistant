package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.UUID

class AppBackupArchiveTest {
    private val now: LocalDateTime = LocalDateTime.of(2026, 4, 17, 12, 0)

    @Test
    fun baseOnlyArchive_reconstructsOriginalBackup() {
        val backup = backup()

        val archive = createAppBackupArchive(backup, now)
        val roundTrippedArchive = fromJSONToAppBackupArchive(fromAppBackupArchiveToJSONPrettyPrint(archive))

        assertEquals(backup, fromIncrementalBackupArchiveToAppBackup(roundTrippedArchive))
        assertEquals(BackupFileType.INCREMENTAL_APP_BACKUP, detectBackupFileType(fromAppBackupArchiveToJSONPrettyPrint(archive)))
    }

    @Test
    fun deltaArchive_reconstructsAddedUpdatedAndDeletedRecords() {
        val previous = backup(
            workoutStore = workoutStore("Before"),
            workoutHistories = listOf(workoutHistory("00000000-0000-0000-0000-000000000001", duration = 10)),
            setHistories = listOf(setHistory("00000000-0000-0000-0000-000000000002", reps = 5)),
            restHistories = listOf(restHistory("00000000-0000-0000-0000-000000000003", seconds = 90)),
            exerciseInfos = listOf(exerciseInfo("00000000-0000-0000-0000-000000000004", successfulSessions = 1u)),
            workoutSchedules = listOf(workoutSchedule("00000000-0000-0000-0000-000000000005", hour = 7)),
            workoutRecords = listOf(workoutRecord("00000000-0000-0000-0000-000000000006", setIndex = 0u)),
            exerciseSessionProgressions = listOf(exerciseSessionProgression("00000000-0000-0000-0000-000000000007", executedVolume = 100.0)),
            errorLogs = listOf(errorLog("error-a", "before"))
        )
        val current = backup(
            workoutStore = workoutStore("After"),
            workoutHistories = listOf(workoutHistory("00000000-0000-0000-0000-000000000001", duration = 20)),
            setHistories = listOf(setHistory("00000000-0000-0000-0000-000000000102", reps = 8)),
            restHistories = listOf(restHistory("00000000-0000-0000-0000-000000000103", seconds = 45)),
            exerciseInfos = listOf(exerciseInfo("00000000-0000-0000-0000-000000000104", successfulSessions = 2u)),
            workoutSchedules = listOf(workoutSchedule("00000000-0000-0000-0000-000000000105", hour = 8)),
            workoutRecords = listOf(workoutRecord("00000000-0000-0000-0000-000000000106", setIndex = 1u)),
            exerciseSessionProgressions = listOf(exerciseSessionProgression("00000000-0000-0000-0000-000000000107", executedVolume = 200.0)),
            errorLogs = listOf(errorLog("error-b", "after"))
        )

        val archive = buildAppBackupArchiveWithCurrentBackup(
            existingArchive = createAppBackupArchive(previous, now),
            currentBackup = current,
            createdAt = now.plusMinutes(1)
        )

        assertEquals(current, fromIncrementalBackupArchiveToAppBackup(archive))
        assertEquals(1, archive.deltas.size)
        assertTrue(archive.deltas.single().workoutStore != null)
        assertEquals(listOf("00000000-0000-0000-0000-000000000002"), archive.deltas.single().setHistories.deletes)
    }

    @Test
    fun hashMismatch_failsReconstruction() {
        val archive = createAppBackupArchive(backup(), now).copy(baseHash = "bad")

        val exception = try {
            fromIncrementalBackupArchiveToAppBackup(archive)
            null
        } catch (e: IllegalArgumentException) {
            e
        }

        assertTrue(exception?.message?.contains("base hash mismatch") == true)
    }

    @Test
    fun existingFullBackupJson_stillParsesAsAppBackup() {
        val backup = backup()
        val json = fromAppBackupToJSONPrettyPrint(backup)

        assertEquals(BackupFileType.APP_BACKUP, detectBackupFileType(json))
        assertEquals(backup, fromBackupJsonToAppBackup(json))
    }

    private fun backup(
        workoutStore: WorkoutStore = workoutStore("Base"),
        workoutHistories: List<WorkoutHistory> = emptyList(),
        setHistories: List<SetHistory> = emptyList(),
        restHistories: List<RestHistory> = emptyList(),
        exerciseInfos: List<ExerciseInfo> = emptyList(),
        workoutSchedules: List<WorkoutSchedule> = emptyList(),
        workoutRecords: List<WorkoutRecord> = emptyList(),
        exerciseSessionProgressions: List<ExerciseSessionProgression> = emptyList(),
        errorLogs: List<ErrorLog> = emptyList(),
    ): AppBackup = AppBackup(
        WorkoutStore = workoutStore,
        WorkoutHistories = workoutHistories,
        SetHistories = setHistories,
        ExerciseInfos = exerciseInfos,
        WorkoutSchedules = workoutSchedules,
        WorkoutRecords = workoutRecords,
        ExerciseSessionProgressions = exerciseSessionProgressions,
        ErrorLogs = errorLogs.takeIf { it.isNotEmpty() },
        RestHistories = restHistories,
    )

    private fun workoutStore(name: String): WorkoutStore = WorkoutStore(
        workouts = listOf(
            Workout(
                id = uuid("10000000-0000-0000-0000-000000000001"),
                name = name,
                description = "",
                workoutComponents = emptyList(),
                order = 0,
                creationDate = LocalDate.of(2026, 4, 17),
                globalId = uuid("10000000-0000-0000-0000-000000000002"),
                type = 0
            )
        ),
        equipments = emptyList(),
        accessoryEquipments = emptyList(),
        workoutPlans = emptyList(),
        birthDateYear = 1990,
        weightKg = 80.0,
        progressionPercentageAmount = 0.1,
    )

    private fun workoutHistory(id: String, duration: Int): WorkoutHistory = WorkoutHistory(
        id = uuid(id),
        workoutId = uuid("10000000-0000-0000-0000-000000000001"),
        date = LocalDate.of(2026, 4, 17),
        time = LocalTime.of(12, 0),
        startTime = now,
        duration = duration,
        heartBeatRecords = emptyList(),
        isDone = true,
        hasBeenSentToHealth = false,
        globalId = uuid("20000000-0000-0000-0000-000000000001"),
    )

    private fun setHistory(id: String, reps: Int): SetHistory = SetHistory(
        id = uuid(id),
        workoutHistoryId = uuid("00000000-0000-0000-0000-000000000001"),
        exerciseId = uuid("30000000-0000-0000-0000-000000000001"),
        setId = uuid("30000000-0000-0000-0000-000000000002"),
        order = 0u,
        startTime = now,
        endTime = now.plusMinutes(1),
        setData = WeightSetData(reps, 50.0, 50.0, SetSubCategory.WorkSet),
        skipped = false,
    )

    private fun restHistory(id: String, seconds: Int): RestHistory = RestHistory(
        id = uuid(id),
        workoutHistoryId = uuid("00000000-0000-0000-0000-000000000001"),
        scope = RestHistoryScope.INTRA_EXERCISE,
        setData = RestSetData(seconds, seconds, SetSubCategory.WorkSet),
        startTime = now,
        endTime = now.plusSeconds(seconds.toLong()),
        exerciseId = uuid("30000000-0000-0000-0000-000000000001"),
        restSetId = uuid("30000000-0000-0000-0000-000000000003"),
        order = 1u,
    )

    private fun exerciseInfo(id: String, successfulSessions: UInt): ExerciseInfo = ExerciseInfo(
        id = uuid(id),
        bestSession = ExerciseSessionSnapshot(),
        lastSuccessfulSession = ExerciseSessionSnapshot(),
        successfulSessionCounter = successfulSessions,
        sessionFailedCounter = 0u,
        lastSessionWasDeload = false,
    )

    private fun workoutSchedule(id: String, hour: Int): WorkoutSchedule = WorkoutSchedule(
        id = uuid(id),
        workoutId = uuid("10000000-0000-0000-0000-000000000002"),
        hour = hour,
        minute = 30,
    )

    private fun workoutRecord(id: String, setIndex: UInt): WorkoutRecord = WorkoutRecord(
        id = uuid(id),
        workoutId = uuid("10000000-0000-0000-0000-000000000001"),
        workoutHistoryId = uuid("00000000-0000-0000-0000-000000000001"),
        setIndex = setIndex,
        exerciseId = uuid("30000000-0000-0000-0000-000000000001"),
    )

    private fun exerciseSessionProgression(id: String, executedVolume: Double): ExerciseSessionProgression =
        ExerciseSessionProgression(
            id = uuid(id),
            workoutHistoryId = uuid("00000000-0000-0000-0000-000000000001"),
            exerciseId = uuid("30000000-0000-0000-0000-000000000001"),
            expectedSets = listOf(SimpleSet(50.0, 5)),
            progressionState = ProgressionState.PROGRESS,
            vsExpected = Ternary.EQUAL,
            vsPrevious = Ternary.ABOVE,
            previousSessionVolume = 100.0,
            expectedVolume = 100.0,
            executedVolume = executedVolume,
        )

    private fun errorLog(id: String, message: String): ErrorLog = ErrorLog(
        id = id,
        timestamp = now,
        threadName = "test",
        exceptionType = "IllegalStateException",
        message = message,
        stackTrace = "stack",
    )

    private fun uuid(value: String): UUID = UUID.fromString(value)
}

