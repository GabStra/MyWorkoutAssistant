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
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
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
) {
    val requiredPermissions = setOf(
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getWritePermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getWritePermission(WeightRecord::class),
    )

    val permissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { permissions ->
        val hasAllPermissions = permissions.values.all { it }
        appViewModel.setHealthPermissions(hasAllPermissions)
    }

    LaunchedEffect(Unit) {
        val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
        val missingPermissions = requiredPermissions - grantedPermissions

        val hasAllPermissions = missingPermissions.isEmpty()
        appViewModel.setHealthPermissions(hasAllPermissions)
        appViewModel.setHealthPermissionsChecked()
    }

    if (appViewModel.checkedHealthPermission && !appViewModel.hasHealthPermissions) {
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