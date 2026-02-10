package com.gabstra.myworkoutassistant.composables

import android.util.Log
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.PermissionController
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ExerciseSessionRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.RestingHeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.TotalCaloriesBurnedRecord
import androidx.health.connect.client.records.WeightRecord
import com.gabstra.myworkoutassistant.AppViewModel
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import kotlinx.coroutines.launch

@Composable
fun HealthConnectHandler(
    appViewModel: AppViewModel,
    healthConnectClient: HealthConnectClient,
) {
    val coroutineScope = rememberCoroutineScope()

    val requiredPermissions = setOf(
        HealthPermission.getWritePermission(ExerciseSessionRecord::class),
        HealthPermission.getWritePermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(ExerciseSessionRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(RestingHeartRateRecord::class),
        HealthPermission.getWritePermission(TotalCaloriesBurnedRecord::class),
        HealthPermission.getWritePermission(WeightRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
    )

    val permissionLauncher = rememberLauncherForActivityResult(
        PermissionController.createRequestPermissionResultContract()
    ) {
        coroutineScope.launch {
            val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
            val missingPermissions = requiredPermissions - grantedPermissions
            appViewModel.setHealthPermissions(missingPermissions.isEmpty())
            appViewModel.setHealthPermissionsChecked()
        }
    }

    LaunchedEffect(Unit) {
        val grantedPermissions = healthConnectClient.permissionController.getGrantedPermissions()
        val missingPermissions = requiredPermissions - grantedPermissions

        val hasAllPermissions = missingPermissions.isEmpty()
        appViewModel.setHealthPermissions(hasAllPermissions)
        appViewModel.setHealthPermissionsChecked()
    }

    if (appViewModel.checkedHealthPermission && !appViewModel.hasHealthPermissions) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(15.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp)
        ) {
            Button(
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background,
                    disabledContentColor = DisabledContentGray
                ),
                onClick = {
                    try {
                        permissionLauncher.launch(requiredPermissions)
                    } catch (e: Exception) {
                        Log.e("MainActivity", "Error launching permission launcher", e)
                    }
                }) {
                Text("Grant Health Connect Permissions", color = MaterialTheme.colorScheme.onPrimary)
            }
        }
    }
}
