package com.gabstra.myworkoutassistant.composables

import android.util.Log
import android.widget.Toast
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.time.Duration
import java.time.Instant
import java.time.ZoneId
import java.time.ZoneOffset

@Composable
fun HealthConnectHandler(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
    workoutHistoryDao: WorkoutHistoryDao,
) {
    val context = LocalContext.current
    var hasAllPermissions by remember { mutableStateOf(false) }

    val requiredPermissions = setOf(
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class)
    )

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        hasAllPermissions = permissions.values.all { it }
    }

    suspend fun CheckPermissions() {
        val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
        val missingPermissions = requiredPermissions - grantedPermissions

        hasAllPermissions = missingPermissions.isEmpty()
    }

    LaunchedEffect(Unit) {
        CheckPermissions()
    }

    val updateMessage by appViewModel.updateNotificationFlow.collectAsState(initial = null)

    LaunchedEffect(updateMessage) {
        withContext(Dispatchers.IO) {
            CheckPermissions()
            if (!hasAllPermissions) return@withContext
            if (appViewModel.workouts.isEmpty()) return@withContext

            try {
                val workoutHistories =
                    workoutHistoryDao.getWorkoutHistoriesByHasBeenSentToHealth(false)
                if (workoutHistories.isEmpty()) return@withContext

                val workoutIds = workoutHistories.map { it.workoutId.toString() }.distinct()
                val workoutsById = appViewModel.workouts.associateBy { it.id }

                healthConnectClient.deleteRecords(
                    recordType = ExerciseSessionRecord::class,
                    emptyList(),
                    workoutIds
                )
                healthConnectClient.deleteRecords(
                    recordType = HeartRateRecord::class,
                    emptyList(),
                    workoutIds
                )

                val exerciseSessionRecords = workoutHistories.map {
                    ExerciseSessionRecord(
                        startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
                        endTime = it.startTime.plusSeconds(it.duration.toLong())
                            .atZone(ZoneId.systemDefault()).toInstant(),
                        startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                        endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                        title = workoutsById[it.workoutId]!!.name,
                        exerciseType = ExerciseSessionRecord.EXERCISE_TYPE_WEIGHTLIFTING,
                        metadata = androidx.health.connect.client.records.metadata.Metadata(
                            clientRecordId = it.workoutId.toString()
                        )
                    )
                }

                val heartRateRecords =
                    workoutHistories.filter { it.heartBeatRecords.isNotEmpty() }.map {
                        HeartRateRecord(
                            startTime = it.startTime.atZone(ZoneId.systemDefault()).toInstant(),
                            endTime = it.startTime.plusSeconds(it.duration.toLong())
                                .atZone(ZoneId.systemDefault()).toInstant(),
                            startZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                            endZoneOffset = ZoneOffset.systemDefault().rules.getOffset(Instant.now()),
                            samples = it.heartBeatRecords.mapIndexed { index, bpm ->
                                HeartRateRecord.Sample(
                                    time = it.startTime.atZone(ZoneId.systemDefault())
                                        .toInstant() + Duration.ofMillis(index.toLong() * 500),
                                    beatsPerMinute = bpm.toLong()
                                )
                            },
                            metadata = androidx.health.connect.client.records.metadata.Metadata(
                                clientRecordId = it.workoutId.toString()
                            )
                        )
                    }

                healthConnectClient.insertRecords(exerciseSessionRecords + heartRateRecords)

                for (workoutHistory in workoutHistories) {
                    workoutHistoryDao.updateHasBeenSentToHealth(workoutHistory.id, true)
                }

                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        "Saved workouts to Health Connect",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            } catch (e: Exception) {
                Log.e("HealthConnectHandler", "Error saving workouts to Health Connect", e)
                withContext(Dispatchers.Main) {
                    Toast.makeText(
                        context,
                        "Failed to save workouts to Health Connect",
                        Toast.LENGTH_SHORT
                    ).show()
                }
            }
        }
    }

    if (!hasAllPermissions) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.Center
        ) {
            Button(
                modifier = Modifier.padding(10.dp),
                colors = ButtonDefaults.buttonColors(contentColor = MaterialTheme.colorScheme.background),
                onClick = {
                    try {
                        permissionLauncher.launch(requiredPermissions.toTypedArray())
                    } catch (e: Exception) {
                        Log.e("MainActivity", "Error launching permission launcher", e)
                    }
                }) {
                Text("Grant Health Connect Permissions")
            }
        }
    }
}