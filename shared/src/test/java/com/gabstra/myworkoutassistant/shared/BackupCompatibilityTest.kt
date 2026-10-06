package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import com.gabstra.myworkoutassistant.shared.motion.resolveMovementJson
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason
import com.gabstra.myworkoutassistant.shared.typeconverters.ListIntConverter
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.util.Base64
import java.util.UUID

class BackupCompatibilityTest {
    @Test
    fun `legacy workout history without end reason defaults to completed`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [
                {
                  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                  "workoutId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                  "date": "2026-01-01",
                  "time": "09:00:00",
                  "startTime": "2026-01-01T09:00:00",
                  "duration": 1200,
                  "heartBeatRecords": [],
                  "isDone": true,
                  "hasBeenSentToHealth": false,
                  "globalId": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                  "version": 0
                }
              ],
              "SetHistories": [],
              "ExerciseInfos": [],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)

        assertEquals(
            com.gabstra.myworkoutassistant.shared.workout.model.WorkoutSessionEndReason.COMPLETED,
            backup.WorkoutHistories.single().endReason
        )
    }

    @Test
    fun `legacy workout history heartbeat decimals deserialize as ints`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [
                {
                  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                  "workoutId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                  "date": "2026-01-01",
                  "time": "09:00:00",
                  "startTime": "2026-01-01T09:00:00",
                  "duration": 1200,
                  "heartBeatRecords": [108.0, 112, "115.0"],
                  "isDone": true,
                  "hasBeenSentToHealth": false,
                  "globalId": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                  "version": 0
                }
              ],
              "SetHistories": [],
              "ExerciseInfos": [],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)

        assertEquals(listOf(108, 112, 115), backup.WorkoutHistories.single().heartBeatRecords)
    }

    @Test
    fun `list int converter tolerates decimal heartbeat storage`() {
        val converter = ListIntConverter()

        assertEquals(listOf(108, 112, 115), converter.toIntList("108.0,112,115.0"))
    }

    @Suppress("UNCHECKED_CAST")
    @Test
    fun `list int converter normalizes erased numeric heartbeat lists before persistence`() {
        val converter = ListIntConverter()

        assertEquals("108,112,115", converter.fromIntList(listOf(108.0, 112, "115.0") as List<Int>))
    }

    @Test
    fun `app backup json round trip preserves integer heartbeat records`() {
        val backup = AppBackup(
            WorkoutStore = WorkoutStore(
                workouts = emptyList(),
                birthDateYear = 1990,
                weightKg = 80.0,
                progressionPercentageAmount = 0.0
            ),
            WorkoutHistories = listOf(
                WorkoutHistory(
                    id = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    workoutId = UUID.fromString("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
                    date = LocalDate.parse("2026-01-01"),
                    time = LocalTime.parse("09:00:00"),
                    startTime = LocalDateTime.parse("2026-01-01T09:00:00"),
                    duration = 1200,
                    heartBeatRecords = listOf(108, 112, 115),
                    isDone = true,
                    hasBeenSentToHealth = false,
                    globalId = UUID.fromString("cccccccc-cccc-cccc-cccc-cccccccccccc"),
                    endReason = WorkoutSessionEndReason.COMPLETED
                )
            ),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList()
        )

        val reparsed = fromJSONtoAppBackup(fromAppBackupToJSON(backup))

        assertEquals(listOf(108, 112, 115), reparsed.WorkoutHistories.single().heartBeatRecords)
    }

    @Test
    fun `app backup json round trip preserves exercise movement backups`() {
        val movementJson = """{"fps":30,"frames":[]}"""
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "test-movement",
            json = movementJson
        )
        val backup = AppBackup(
            WorkoutStore = WorkoutStore(
                workouts = emptyList(),
                birthDateYear = 1990,
                weightKg = 80.0,
                progressionPercentageAmount = 0.0
            ),
            WorkoutHistories = emptyList(),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
            ExerciseMovements = listOf(
                ExerciseMovementBackup(
                    movementRef = movementRef,
                    json = movementJson
                )
            )
        )

        val reparsed = fromJSONtoAppBackup(fromAppBackupToJSON(backup))

        assertEquals(backup.ExerciseMovements, reparsed.ExerciseMovements)
    }

    @Test
    fun `app backup json round trip preserves compressed exercise movement backups`() {
        val movementJson = """{"fps":30,"frames":[{"joints":{"pelvis":[0,1,0]}}]}"""
        val movementRef = ExerciseMovementRef.forWearSkeletonJson(
            movementId = "compressed-test-movement",
            json = movementJson
        )
        val backup = AppBackup(
            WorkoutStore = WorkoutStore(
                workouts = emptyList(),
                birthDateYear = 1990,
                weightKg = 80.0,
                progressionPercentageAmount = 0.0
            ),
            WorkoutHistories = emptyList(),
            SetHistories = emptyList(),
            ExerciseInfos = emptyList(),
            WorkoutSchedules = emptyList(),
            WorkoutRecords = emptyList(),
            ExerciseSessionProgressions = emptyList(),
            ExerciseMovements = listOf(
                ExerciseMovementBackup(
                    movementRef = movementRef,
                    compressedJsonBase64 = Base64.getEncoder().encodeToString(compressString(movementJson)),
                    compression = ExerciseMovementBackup.COMPRESSION_GZIP_BASE64
                )
            )
        )

        val reparsedMovement = fromJSONtoAppBackup(fromAppBackupToJSON(backup)).ExerciseMovements!!.single()

        assertNull(reparsedMovement.json)
        assertEquals(ExerciseMovementBackup.COMPRESSION_GZIP_BASE64, reparsedMovement.compression)
        assertEquals(movementJson, reparsedMovement.resolveMovementJson())
    }

    @Suppress("UNCHECKED_CAST")
    @Test
    fun `workout history normalization coerces erased numeric heartbeat records to ints`() {
        val malformedHistory = WorkoutHistory(
            id = UUID.fromString("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            workoutId = UUID.fromString("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            date = LocalDate.parse("2026-01-01"),
            time = LocalTime.parse("09:00:00"),
            startTime = LocalDateTime.parse("2026-01-01T09:00:00"),
            duration = 1200,
            heartBeatRecords = listOf(108.0, 112, "115.0") as List<Int>,
            isDone = true,
            hasBeenSentToHealth = false,
            globalId = UUID.fromString("cccccccc-cccc-cccc-cccc-cccccccccccc"),
            endReason = WorkoutSessionEndReason.COMPLETED
        )

        val normalizedHistory = malformedHistory.normalizedHeartBeatRecords()

        assertEquals(listOf(108, 112, 115), normalizedHistory.heartBeatRecords)
        assertEquals("108,112,115", ListIntConverter().fromIntList(normalizedHistory.heartBeatRecords))
    }

    @Test
    fun `old backup workout records deserialize with default active session metadata`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [],
              "SetHistories": [],
              "ExerciseInfos": [],
              "WorkoutSchedules": [],
              "WorkoutRecords": [
                {
                  "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                  "workoutId": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
                  "workoutHistoryId": "cccccccc-cccc-cccc-cccc-cccccccccccc",
                  "setIndex": 2,
                  "exerciseId": "dddddddd-dddd-dddd-dddd-dddddddddddd"
                }
              ],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)
        val workoutRecord = backup.WorkoutRecords.single()

        assertEquals("PHONE", workoutRecord.ownerDevice)
        assertEquals(0u, workoutRecord.activeSessionRevision)
        assertNull(workoutRecord.lastActiveSyncAt)
        assertNull(workoutRecord.lastKnownSessionState)
        assertEquals(2u, workoutRecord.setIndex)
    }

    @Test
    fun `legacy set json uses default shouldReapplyHistoryToSet values`() {
        val gson = GsonBuilder()
            .registerTypeAdapter(Set::class.java, SetAdapter())
            .create()

        val legacyWeightSetJson = """
            {
              "id": "33333333-3333-3333-3333-333333333333",
              "type": "WeightSet",
              "reps": 8,
              "weight": 100.0,
              "subCategory": "WorkSet"
            }
        """.trimIndent()
        val legacyRestSetJson = """
            {
              "id": "44444444-4444-4444-4444-444444444444",
              "type": "RestSet",
              "timeInSeconds": 90,
              "subCategory": "WorkSet"
            }
        """.trimIndent()

        val workSet = gson.fromJson(legacyWeightSetJson, Set::class.java) as WeightSet
        val restSet = gson.fromJson(legacyRestSetJson, Set::class.java) as RestSet

        assertTrue(workSet.shouldReapplyHistoryToSet)
        assertFalse(restSet.shouldReapplyHistoryToSet)
    }

    @Test
    fun `legacy exercise info sessions deserialize from set history arrays`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [],
              "SetHistories": [],
              "ExerciseInfos": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "bestSession": [
                    {
                      "id": "22222222-2222-2222-2222-222222222222",
                      "setId": "33333333-3333-3333-3333-333333333333",
                      "order": 0,
                      "startTime": "2026-01-01T10:00:00",
                      "endTime": "2026-01-01T10:01:00",
                      "setData": {
                        "type": "WeightSetData",
                        "actualReps": 8,
                        "actualWeight": 100.0,
                        "volume": 800.0,
                        "subCategory": "WorkSet",
                        "calibrationRIR": null
                      },
                      "skipped": false,
                      "exerciseId": "11111111-1111-1111-1111-111111111111"
                    }
                  ],
                  "lastSuccessfulSession": [
                    {
                      "id": "44444444-4444-4444-4444-444444444444",
                      "setId": "55555555-5555-5555-5555-555555555555",
                      "order": 0,
                      "startTime": "2026-01-01T10:00:00",
                      "endTime": "2026-01-01T10:01:00",
                      "setData": {
                        "type": "RestSetData",
                        "startTimer": 90,
                        "endTimer": 70,
                        "subCategory": "WorkSet"
                      },
                      "skipped": false,
                      "exerciseId": "11111111-1111-1111-1111-111111111111"
                    }
                  ],
                  "successfulSessionCounter": 1,
                  "sessionFailedCounter": 0,
                  "lastSessionWasDeload": false,
                  "timesCompletedInAWeek": 1,
                  "weeklyCompletionUpdateDate": "2026-01-01",
                  "version": 0
                }
              ],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)
        val exerciseInfo = backup.ExerciseInfos.single()

        assertEquals(1, exerciseInfo.bestSession.sets.size)
        assertTrue(exerciseInfo.bestSession.sets.single().set is WeightSet)
        assertEquals(1, exerciseInfo.lastSuccessfulSession.sets.size)
        assertTrue(exerciseInfo.lastSuccessfulSession.sets.single().set is RestSet)
    }

    @Test
    fun `legacy exercise session snapshot sets deserialize without explicit set type`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [],
              "SetHistories": [],
              "ExerciseInfos": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "bestSession": {
                    "sets": [
                      {
                        "setId": "33333333-3333-3333-3333-333333333333",
                        "set": {
                          "id": "33333333-3333-3333-3333-333333333333",
                          "reps": 8,
                          "weight": 100.0,
                          "subCategory": "WorkSet",
                          "shouldReapplyHistoryToSet": true
                        },
                        "simpleSet": {
                          "reps": 8,
                          "weight": 100.0
                        },
                        "wasExecuted": true,
                        "wasSkipped": false
                      }
                    ]
                  },
                  "lastSuccessfulSession": {
                    "sets": [
                      {
                        "setId": "55555555-5555-5555-5555-555555555555",
                        "set": {
                          "id": "55555555-5555-5555-5555-555555555555",
                          "timeInSeconds": 90,
                          "subCategory": "WorkSet",
                          "shouldReapplyHistoryToSet": false
                        },
                        "simpleSet": null,
                        "wasExecuted": true,
                        "wasSkipped": false
                      }
                    ]
                  },
                  "successfulSessionCounter": 1,
                  "sessionFailedCounter": 0,
                  "lastSessionWasDeload": false,
                  "timesCompletedInAWeek": 1,
                  "weeklyCompletionUpdateDate": "2026-01-01",
                  "version": 0
                }
              ],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)
        val exerciseInfo = backup.ExerciseInfos.single()

        assertEquals(1, exerciseInfo.bestSession.sets.size)
        assertTrue(exerciseInfo.bestSession.sets.single().set is WeightSet)
        assertEquals(1, exerciseInfo.lastSuccessfulSession.sets.size)
        assertTrue(exerciseInfo.lastSuccessfulSession.sets.single().set is RestSet)
    }

    @Test
    fun `legacy exercise session snapshot falls back to simple set when concrete set payload is too old`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [],
              "SetHistories": [],
              "ExerciseInfos": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "bestSession": {
                    "sets": [
                      {
                        "setId": "33333333-3333-3333-3333-333333333333",
                        "set": {
                          "id": "33333333-3333-3333-3333-333333333333",
                          "subCategory": "WorkSet",
                          "shouldReapplyHistoryToSet": true
                        },
                        "simpleSet": {
                          "weight": 100.0,
                          "reps": 8
                        },
                        "wasExecuted": true,
                        "wasSkipped": false
                      }
                    ]
                  },
                  "lastSuccessfulSession": {
                    "sets": []
                  },
                  "successfulSessionCounter": 1,
                  "sessionFailedCounter": 0,
                  "lastSessionWasDeload": false,
                  "timesCompletedInAWeek": 1,
                  "weeklyCompletionUpdateDate": "2026-01-01",
                  "version": 0
                }
              ],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)
        val set = backup.ExerciseInfos.single().bestSession.sets.single().set as WeightSet

        assertEquals(8, set.reps)
        assertEquals(100.0, set.weight, 0.0)
        assertTrue(set.shouldReapplyHistoryToSet)
    }

    @Test
    fun `legacy exercise session snapshot infers rest set from id and no reapply flag only`() {
        val backupJson = """
            {
              "WorkoutStore": {
                "workouts": [],
                "polarDeviceId": null,
                "birthDateYear": 1990,
                "weightKg": 80.0,
                "equipments": [],
                "workoutPlans": [],
                "progressionPercentageAmount": 0.0,
                "measuredMaxHeartRate": null,
                "restingHeartRate": null
              },
              "WorkoutHistories": [],
              "SetHistories": [],
              "ExerciseInfos": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "bestSession": {
                    "sets": []
                  },
                  "lastSuccessfulSession": {
                    "sets": [
                      {
                        "setId": "ce763d5f-45d6-4b82-a32e-d913a4ccbdab",
                        "set": {
                          "id": "ce763d5f-45d6-4b82-a32e-d913a4ccbdab",
                          "shouldReapplyHistoryToSet": false
                        },
                        "simpleSet": null,
                        "wasExecuted": true,
                        "wasSkipped": false
                      }
                    ]
                  },
                  "successfulSessionCounter": 1,
                  "sessionFailedCounter": 0,
                  "lastSessionWasDeload": false,
                  "timesCompletedInAWeek": 1,
                  "weeklyCompletionUpdateDate": "2026-01-01",
                  "version": 0
                }
              ],
              "WorkoutSchedules": [],
              "WorkoutRecords": [],
              "ExerciseSessionProgressions": []
            }
        """.trimIndent()

        val backup = fromJSONtoAppBackup(backupJson)
        val set = backup.ExerciseInfos.single().lastSuccessfulSession.sets.single().set as RestSet

        assertFalse(set.shouldReapplyHistoryToSet)
        assertEquals(0, set.timeInSeconds)
    }
}
