package com.gabstra.myworkoutassistant.shared.motion

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.ExerciseDefinition
import com.gabstra.myworkoutassistant.shared.ExerciseMovementBackup
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.assertThrows
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import java.io.File
import java.time.LocalDate
import java.util.UUID

@RunWith(RobolectricTestRunner::class)
class ExerciseMovementStorageTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @Test
    fun `write movement stores gzip and reads json on demand`() {
        val movementJson = repeatedMovementJson()
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "storage-compression-${UUID.randomUUID()}",
            json = movementJson,
        )

        ExerciseMovementStorage.writeMovementJson(context, movementRef, movementJson)

        assertEquals(movementJson, ExerciseMovementStorage.readMovementJson(context, movementRef))
        val movementFiles = movementDirectory().listFiles().orEmpty()
            .filter { file -> file.name.contains(movementRef.movementId.take(20)) }
        assertTrue(movementFiles.any { file -> file.name.endsWith(".json.gz") })
        assertFalse(movementFiles.any { file -> file.name.endsWith(".json") })
        assertNotNull(ExerciseMovementStorage.readCompressedMovementJsonBytes(context, movementRef))
    }

    @Test
    fun `collect backups emits compressed movement payloads`() {
        val movementJson = repeatedMovementJson()
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "backup-compression-${UUID.randomUUID()}",
            json = movementJson,
        )
        ExerciseMovementStorage.writeMovementJson(context, movementRef, movementJson)

        val backup = collectExerciseMovementBackups(context, workoutStoreWithMovement(movementRef)).single()

        assertEquals(movementRef, backup.movementRef)
        assertEquals(null, backup.json)
        assertEquals(ExerciseMovementBackup.COMPRESSION_GZIP_BASE64, backup.compression)
        assertEquals(movementJson, backup.resolveMovementJson())
    }

    @Test
    fun `collect backups includes movements used only by library definitions`() {
        val movementJson = repeatedMovementJson()
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "library-only-${UUID.randomUUID()}",
            json = movementJson,
        )
        ExerciseMovementStorage.writeMovementJson(context, movementRef, movementJson)
        val workoutStore = WorkoutStore(
            exerciseDefinitions = listOf(
                ExerciseDefinition(
                    id = UUID.randomUUID(),
                    name = "Library-only movement",
                    exerciseType = ExerciseType.WEIGHT,
                    movementRef = movementRef,
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0,
        )

        val backup = collectExerciseMovementBackups(context, workoutStore).single()

        assertEquals(movementRef, backup.movementRef)
        assertEquals(movementJson, backup.resolveMovementJson())
        requireExerciseMovementPayloads(context, workoutStore)
    }

    @Test
    fun `movement payload validation rejects a dangling library reference`() {
        val movementJson = repeatedMovementJson()
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "missing-library-${UUID.randomUUID()}",
            json = movementJson,
        )
        val workoutStore = WorkoutStore(
            exerciseDefinitions = listOf(
                ExerciseDefinition(
                    id = UUID.randomUUID(),
                    name = "Missing library movement",
                    exerciseType = ExerciseType.WEIGHT,
                    movementRef = movementRef,
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0,
        )

        assertThrows(IllegalArgumentException::class.java) {
            requireExerciseMovementPayloads(context, workoutStore)
        }
        assertThrows(IllegalArgumentException::class.java) {
            collectExerciseMovementBackups(context, workoutStore)
        }
    }

    @Test
    fun `restore backups accepts compressed movement payloads`() {
        val movementJson = repeatedMovementJson()
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "restore-compression-${UUID.randomUUID()}",
            json = movementJson,
        )
        ExerciseMovementStorage.writeMovementJson(context, movementRef, movementJson)
        val backup = collectExerciseMovementBackups(context, workoutStoreWithMovement(movementRef)).single()

        val restoredMovementRef = movementRef.copy(movementId = "restored-${movementRef.movementId}")
        restoreExerciseMovementBackups(context, listOf(backup.copy(movementRef = restoredMovementRef)))

        assertEquals(movementJson, ExerciseMovementStorage.readMovementJson(context, restoredMovementRef))
    }

    private fun workoutStoreWithMovement(movementRef: ExerciseMovementRef): WorkoutStore {
        val exercise = Exercise(
            id = UUID.randomUUID(),
            enabled = true,
            name = "Movement test",
            notes = "",
            sets = emptyList(),
            exerciseType = ExerciseType.WEIGHT,
            minReps = 4,
            maxReps = 12,
            lowerBoundMaxHRPercent = null,
            upperBoundMaxHRPercent = null,
            equipmentId = null,
            bodyWeightPercentage = null,
            movementRef = movementRef,
        )
        return WorkoutStore(
            workouts = listOf(
                Workout(
                    id = UUID.randomUUID(),
                    name = "Movement storage test",
                    description = "",
                    workoutComponents = listOf(exercise),
                    order = 0,
                    enabled = true,
                    creationDate = LocalDate.now(),
                    previousVersionId = null,
                    nextVersionId = null,
                    isActive = true,
                    timesCompletedInAWeek = null,
                    globalId = UUID.randomUUID(),
                    type = 0,
                )
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0,
        )
    }

    private fun repeatedMovementJson(): String {
        val frames = (0 until 120).joinToString(separator = ",") { frame ->
            """{"joints":{"pelvis":[0,$frame,0],"head":[0,${frame + 1},0]}}"""
        }
        return """{"fps":30,"frames":[$frames]}"""
    }

    private fun movementDirectory(): File = File(context.filesDir, "exercise_movements")
}
