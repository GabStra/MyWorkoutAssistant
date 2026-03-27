package com.gabstra.myworkoutassistant.shared

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HeartRateSourceMigrationTest {
    @Test
    fun `legacy workout usePolarDevice migrates to Polar heart rate source`() {
        val legacyWorkoutStoreJson = """
            {
              "workouts": [
                {
                  "id": "11111111-1111-1111-1111-111111111111",
                  "name": "Legacy Polar Workout",
                  "description": "",
                  "workoutComponents": [],
                  "order": 0,
                  "enabled": true,
                  "usePolarDevice": true,
                  "creationDate": "2026-01-01",
                  "isActive": true,
                  "timesCompletedInAWeek": null,
                  "globalId": "22222222-2222-2222-2222-222222222222",
                  "type": 0,
                  "workoutPlanId": null
                }
              ],
              "equipments": [],
              "accessoryEquipments": [],
              "workoutPlans": [],
              "weeklyProgressOverrides": [],
              "polarDeviceId": null,
              "birthDateYear": 1990,
              "weightKg": 80.0,
              "progressionPercentageAmount": 0.0,
              "measuredMaxHeartRate": null,
              "restingHeartRate": null
            }
        """.trimIndent()

        val workoutStore = fromJSONToWorkoutStore(legacyWorkoutStoreJson)

        assertEquals(HeartRateSource.POLAR_BLE, workoutStore.workouts.single().heartRateSource)
    }

    @Test
    fun `legacy workout store polarDeviceId migrates to Polar config`() {
        val legacyWorkoutStoreJson = """
            {
              "workouts": [],
              "equipments": [],
              "accessoryEquipments": [],
              "workoutPlans": [],
              "weeklyProgressOverrides": [],
              "polarDeviceId": "POLAR-DEVICE-123",
              "birthDateYear": 1990,
              "weightKg": 80.0,
              "progressionPercentageAmount": 0.0,
              "measuredMaxHeartRate": null,
              "restingHeartRate": null
            }
        """.trimIndent()

        val workoutStore = fromJSONToWorkoutStore(legacyWorkoutStoreJson)

        val config = workoutStore.externalHeartRateConfigs.single() as PolarHeartRateConfig
        assertEquals("POLAR-DEVICE-123", config.deviceId)
    }

    @Test
    fun `external heart rate configs round trip with concrete types preserved`() {
        val workoutStore = WorkoutStore(
            workouts = listOf(
                Workout(
                    id = java.util.UUID.fromString("11111111-1111-1111-1111-111111111111"),
                    name = "WHOOP Workout",
                    description = "",
                    workoutComponents = emptyList(),
                    order = 0,
                    heartRateSource = HeartRateSource.WHOOP_BLE,
                    creationDate = java.time.LocalDate.of(2026, 1, 1),
                    globalId = java.util.UUID.fromString("22222222-2222-2222-2222-222222222222"),
                    type = 0
                )
            ),
            externalHeartRateConfigs = listOf(
                PolarHeartRateConfig(deviceId = "POLAR-1", displayName = "Polar H10"),
                WhoopHeartRateConfig(deviceId = "WHOOP-1", displayName = "WHOOP Arm")
            ),
            birthDateYear = 1990,
            weightKg = 80.0,
            progressionPercentageAmount = 0.0
        )

        val json = fromWorkoutStoreToJSON(workoutStore)
        val decoded = fromJSONToWorkoutStore(json)

        assertEquals(HeartRateSource.WHOOP_BLE, decoded.workouts.single().heartRateSource)
        assertTrue(decoded.externalHeartRateConfigs.any { it is PolarHeartRateConfig })
        assertTrue(decoded.externalHeartRateConfigs.any { it is WhoopHeartRateConfig })
    }
}
