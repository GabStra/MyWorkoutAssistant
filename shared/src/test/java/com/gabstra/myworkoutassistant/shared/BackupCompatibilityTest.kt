package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.google.gson.GsonBuilder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class BackupCompatibilityTest {
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
